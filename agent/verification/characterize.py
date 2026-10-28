"""Characterization journeys written by the QA sub-agent (CODEWRIGHT.md Phase 7 task 2, Section 6: QA Engineer →
Test Writer).

The model sees one group of routes at a time (one resource: `/products…`), the handlers that read a request body
and the request types they bind, and the values earlier journeys saved (`{{token}}`, `{{product_id}}`). It writes a
short journey that exercises the group the way a client would. Each draft is run on the live app at once; a step the
app rejects as malformed (400/422) goes back to the model with the app's answer, once. The kept journeys are saved
as JSON the user can read and edit; recordings are made from them, so later runs don't need the model.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from agent.chat.explain import definition_pattern, definitions, source_files
from agent.llm.client import LLMClient
from agent.llm.structured import StructuredOutputError, structured
from agent.verification.journeys import Journey, Route, Step, run_journeys
from agent.verification.traffic import Recording

MAX_GROUPS = 14
LOGIN = "login"  # the group that creates a test user and logs in; it runs first
CODE_BUDGET = 5200  # characters of handler and type source per group (the model has a 4K-token context)
AUTH = re.compile(r"(register|signup|sign-up|login|signin|sign-in|token|session)", re.I)
SKIP = re.compile(r"(webhook|swagger|openapi|metrics|debug|pprof|/docs\b)", re.I)
TYPE_HINT = re.compile(r"(Req|Request|Input|Body|Dto|DTO|Payload|Params|Schema|Form|Create|Update|In)$")
Notify = Callable[[str], Awaitable[None]]

QA_RULES = """You are the QA Test Writer. Write ONE short journey of HTTP requests that exercises these routes the way \
a real client would, so their current behavior can be recorded.

Rules:
- Use only the routes listed, with their paths exactly as listed; put saved values in paths as {{name}}.
- Create before you read, update or delete: save the new item's id from the create answer and use it later.
- Bodies must match the request types in the code (field names exactly as the JSON tags or field names say).
  Use plain, realistic test values. Body is a JSON string, or "" when the request has none.
- Set auth to true for routes that need a logged-in user (the code checks a token or middleware).
- save: values later steps need, as {"var": name, "from": JSON path in the answer like $.data.id}.
- At most 8 steps. Don't delete something you still need afterwards."""

AUTH_RULES = """You are the QA Test Writer. Write ONE short journey that creates a test user and logs in, so later \
requests can be authenticated.

Rules:
- Use only the routes listed, with their paths exactly as listed.
- Bodies must match the request types in the code (field names exactly as the JSON tags or field names say).
  Use test values: email qa.tester@example.com, password Test-Pass-123!, name QA Tester (adapt to the fields).
- In the login step, save the access token as {"var": "token", "from": JSON path to it in the answer}.
- At most 4 steps."""


class SaveOut(BaseModel):
    var: str = Field(description="Variable name, e.g. product_id")
    from_: str = Field(alias="from", description="JSON path in the answer, e.g. $.data.id")


class StepOut(BaseModel):
    name: str = Field(description="What the step does, e.g. 'create a product'")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(description="A listed path; {{var}} for saved values, e.g. /products/{{product_id}}")
    body_json: str = Field(description='JSON body as a string, or "" for none')
    auth: bool = Field(description="True when the route needs the logged-in user's token")
    save: list[SaveOut] = Field(default_factory=list)


class JourneyOut(BaseModel):
    steps: list[StepOut] = Field(max_length=8)


# ── grouping ────────────────────────────────────────────────────────────────
def groups(found: list[Route]) -> list[tuple[str, list[Route]]]:
    """Routes by resource (the first path segment), the auth routes first; groups with nothing to write and no
    parameters are left to the smoke journey."""
    by: dict[str, list[Route]] = {}
    kept = [r for r in found if not SKIP.search(r.path)]
    shared = _shared_segments([r.path for r in kept if r.path.count("/") > 1])
    for r in kept:
        words = [s for s in r.path.split("/") if s and not s.startswith("{")]
        if words[: len(shared)] == shared and len(words) > len(shared):
            words = words[len(shared) :]  # /api/notes and /api/auth/login: group by notes, auth
        by.setdefault(words[0] if words else "/", []).append(r)
    auth = [r for r in found if AUTH.search(r.path) and r.method in ("POST", "PUT") and not SKIP.search(r.path)]
    out: list[tuple[str, list[Route]]] = []
    if auth:
        out.append((LOGIN, auth))
    for name, rs in by.items():
        rest = [r for r in rs if r not in auth]
        if any(r.method != "GET" or not r.plain for r in rest):
            out.append((name, rest))
    return out[: MAX_GROUPS + 1]


def _shared_segments(paths: list[str]) -> list[str]:
    """Leading segments every path has (`api`, `v1`): they say nothing about the resource."""
    split = [[s for s in p.split("/") if s] for p in paths]
    shared: list[str] = []
    for i, word in enumerate(split[0] if split else []):
        if word.startswith("{") or any(len(p) <= i + 1 or p[i] != word for p in split):
            break
        shared.append(word)
    return shared


def dependency_order(named: list[tuple[str, list[Route], str]]) -> list[tuple[str, list[Route], str]]:
    """Groups others depend on first: a resource whose name appears in other groups' code (`product` in the order
    handler) is created before them, so its saved ID is there to use. The login group stays first."""

    def used_by(name: str) -> int:
        word = re.compile(rf"\b{re.escape(name.rstrip('s'))}", re.I)
        return sum(1 for other, _, code in named if other != name and word.search(code))

    login = [g for g in named if g[0] == LOGIN]
    rest = sorted((g for g in named if g[0] != LOGIN), key=lambda g: -used_by(g[0]))
    return login + rest


def handler_name(handler: str) -> str:
    """`productHandler.CreateProduct` → CreateProduct; `middleware.JWTAuth(` (a middleware, not a handler) → ""."""
    name = handler.strip().rstrip("(").split("(")[0].rsplit(".", 1)[-1]
    return name if re.fullmatch(r"[A-Za-z_]\w*", name) and "auth" not in name.lower() else ""


def code_for(work: Path, rs: list[Route], budget: int = CODE_BUDGET) -> str:
    """The write handlers of a group and the request types they read, within `budget` characters."""
    files = source_files(work)
    parts: list[str] = []
    shown: set[tuple[str, int]] = set()
    names = [handler_name(r.handler) for r in rs if r.method in ("POST", "PUT", "PATCH")]
    for name in dict.fromkeys(n for n in names if n):
        parts += definitions(work, name, limit=1, budget=max(budget // 3, 600), files=files, shown=shown)
    body = "\n".join(parts)
    types = [w for w in dict.fromkeys(re.findall(r"\b([A-Z]\w{2,})\b", body)) if TYPE_HINT.search(w)]
    for name in types[:6]:
        room = budget - len("\n".join(parts))
        if room < 400:
            break
        if any(definition_pattern(name).match(line) for _, lines in files for line in lines):
            parts += definitions(work, name, limit=1, budget=room, files=files, shown=shown)
    return "\n".join(parts)[:budget]


def _prompt(name: str, rs: list[Route], code: str, variables: dict[str, Any], errors: str = "") -> str:
    listed = "\n".join(f"- {r.method} {r.path}" for r in rs)
    saved = ", ".join(f"{{{{{k}}}}} = {json.dumps(v)[:60]}" for k, v in variables.items()) or "none yet"
    text = f"Routes ({name}):\n{listed}\n\nValues saved by earlier journeys: {saved}\n\nCode:\n{code or '(not found)'}"
    if errors:
        text += f"\n\nYour last journey was rejected by the app:\n{errors}\nFix the bodies or paths."
    return text


def to_journey(name: str, out: JourneyOut, routes_: list[Route], prefix: str) -> Journey:
    known = {(r.method, r.path) for r in routes_}
    steps = []
    for s in out.steps:
        path = "/" + s.path.strip().lstrip("/")
        if prefix and path.startswith(prefix + "/"):
            path = path[len(prefix) :]  # the model copied a path as sent (an error shows it with the prefix)
        template = re.sub(r"\{\{\s*\w+\s*\}\}", "{}", path)
        if not any(m == s.method and re.sub(r"\{\w+\}", "{}", p) == template for m, p in known):
            continue  # not a route of this group: the model made it up
        try:
            body = json.loads(s.body_json) if s.body_json.strip() and s.method not in ("GET", "DELETE") else None
        except ValueError:
            body = None
        headers = {"Authorization": "Bearer {{token}}"} if s.auth else {}
        steps.append(Step(s.name, s.method, prefix + path, body, headers, {v.var: v.from_ for v in s.save}))
    return Journey(name, steps, "qa", f"{len(steps)} requests on {name} written by the QA sub-agent")


def _rejected(recording: Recording, start: int) -> str:
    """Steps the app refused as malformed (400, 422) or for a missing login (401), with its answer."""
    lines = []
    for ex in recording.exchanges[start:]:
        if ex.response is not None and ex.response.status in (400, 401, 422):
            answer = json.dumps(ex.response.body.value)[:300] if ex.response.body.kind == "json" else ""
            body = json.dumps(ex.request.body.value)[:200] if ex.request.body.kind == "json" else ""
            hint = " (this route needs the login token: set auth to true)" if ex.response.status == 401 else ""
            lines.append(f"{ex.request.method} {ex.request.path} {body} → {ex.response.status} {answer}{hint}")
    return "\n".join(lines[:4])


def _statuses(recording: Recording, start: int) -> str:
    return ", ".join(
        f"{ex.request.method} {ex.request.path} {ex.response.status if ex.response else 'no answer'}"
        for ex in recording.exchanges[start:]
    )


async def write_journeys(
    client: LLMClient,
    work: Path,
    found: list[Route],
    prefix: str,
    base_url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    notify: Notify | None = None,
) -> list[Journey]:
    """Draft, try and keep one journey per route group. The drafts run on the live app (state changes there are
    thrown away: recordings start from a reset)."""
    kept: list[Journey] = []
    variables: dict[str, Any] = {}
    scratch = Recording("draft", "journeys", {})
    named = [(name, rs, await asyncio.to_thread(code_for, work, rs)) for name, rs in groups(found)]
    for name, rs, code in dependency_order(named):
        if notify is not None:
            await notify(f"QA Test Writer: {name} ({len(rs)} routes)")
        errors = ""
        best: tuple[int, Journey] | None = None  # (steps the app accepted, journey): a worse retry doesn't replace it
        for _attempt in range(2):
            try:
                result = await structured(
                    client,
                    JourneyOut,
                    [
                        {"role": "system", "content": AUTH_RULES if name == LOGIN else QA_RULES},
                        {"role": "user", "content": _prompt(name, rs, code, variables, errors)},
                    ],
                    task="qa_journey",
                    max_tokens=1100,
                )
            except StructuredOutputError:
                if notify is not None:  # the smoke journey still covers the group's plain GETs
                    await notify(f"  no usable journey for {name} from the model; skipped")
                break
            journey = to_journey(name, result.value, rs, prefix)
            start = len(scratch.exchanges)
            variables |= await run_journeys([journey], base_url, recording=scratch, transport=transport,
                                            variables=variables)  # fmt: skip
            errors = _rejected(scratch, start)
            if notify is not None:
                await notify(f"  tried: {_statuses(scratch, start) or 'no steps on known routes'}")
            accepted = sum(1 for ex in scratch.exchanges[start:] if ex.response and ex.response.status < 400)
            if journey.steps and (best is None or accepted > best[0]):
                best = (accepted, journey)
            if not errors:
                break
        if best is not None:
            kept.append(best[1])
    return kept
