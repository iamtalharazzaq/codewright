"""Journeys: request sequences Codewright sends to an app to record how it behaves (characterization by traffic,
CODEWRIGHT.md Phase 7 tasks 2-3).

A journey is plain JSON the user can read and edit: steps with a method, a path, a body and headers, where
`{{name}}` is a value saved from an earlier answer (`save: {"token": "$.data.access_token"}`). Running journeys
against the app produces a `Recording`; the recording, not the journeys, is what a replay sends again.

Two sources: a **smoke** journey built from the routes the Language Packs found (every GET without parameters),
and journeys the QA sub-agent writes from the routes and their handler code (`characterize.py`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from agent.language_packs import detect_project, pack
from agent.language_packs.base import walk
from agent.verification.noise import JWT
from agent.verification.replay import send
from agent.verification.traffic import Body, Exchange, Recording, Request

VAR = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}")
SESSION = "journeys"  # one cookie jar for all journeys: a login in one journey holds for the next
OnExchange = Callable[[Exchange], Awaitable[None]]


@dataclass
class Step:
    name: str
    method: str
    path: str
    body: Any = None  # JSON value, or None
    headers: dict[str, str] = field(default_factory=dict)
    save: dict[str, str] = field(default_factory=dict)  # variable → JSON path in the answer ($.data.id)


@dataclass
class Journey:
    name: str
    steps: list[Step]
    source: str = "smoke"  # smoke, qa, user
    about: str = ""


def journeys_from_json(data: list[dict[str, Any]]) -> list[Journey]:
    out = []
    for j in data:
        steps = [Step(**{k: v for k, v in s.items() if k in Step.__dataclass_fields__}) for s in j.get("steps", [])]
        out.append(Journey(j["name"], steps, j.get("source", "user"), j.get("about", "")))
    return out


def save_journeys(journeys: list[Journey], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(j) for j in journeys], indent=2) + "\n", encoding="utf-8")


def load_journeys(path: Path) -> list[Journey]:
    try:
        return journeys_from_json(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else []
    except (ValueError, KeyError, TypeError):
        return []


# ── routes ──────────────────────────────────────────────────────────────────
@dataclass
class Route:
    method: str
    path: str  # with {param} placeholders, as the code declares it (no group prefix)
    file: str
    line: int
    handler: str = ""

    @property
    def params(self) -> list[str]:
        return re.findall(r"\{(\w+)\}", self.path)

    @property
    def plain(self) -> bool:
        return not self.params and "*" not in self.path


def normalize(path: str) -> str:
    """Framework route syntax → `{param}`: `:id` (gin, Express), `<int:id>` (Flask), `[id]` (Next.js). Flask's goes
    first: its own `:` would otherwise be caught by the gin-style substitution."""
    path = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", path)
    path = re.sub(r":(\w+)", r"{\1}", path)
    path = re.sub(r"\[(?:\.\.\.)?(\w+)\]", r"{\1}", path)
    return path


def routes(work: Path, component: str | None = None) -> list[Route]:
    """HTTP routes the Language Packs found, for one component (or all)."""
    out: list[Route] = []
    for c in detect_project(work):
        if component is not None and c.path != component:
            continue
        for n in pack(c.pack).parse(work, c).as_dict()["nodes"]:
            if n["kind"] != "route":
                continue
            method, _, path = n["label"].partition(" ")
            out.append(Route(method.upper(), normalize(path), n["file"], n["line"], n.get("handler", "") or ""))
    return out


MAX_PAGES = 20


def pages(work: Path, component: str | None = None, limit: int = MAX_PAGES) -> list[str]:
    """Web pages the Language Packs found (React Router, Next.js) that open without parameters: `/`, `/cart`."""
    out: list[str] = []
    for c in detect_project(work):
        if component is not None and c.path != component:
            continue
        for n in pack(c.pack).parse(work, c).as_dict()["nodes"]:
            path = normalize(str(n["label"]))
            if n["kind"] == "page" and path.startswith("/") and "{" not in path and "*" not in path and path not in out:
                out.append(path)
    return sorted(out, key=lambda p: (p != "/", p.count("/"), p))[:limit]


_PREFIX = [
    re.compile(r"""\.Group\(\s*["'`](/[\w./-]*)["'`]"""),  # gin, echo, fiber, chi
    re.compile(r"""(?:url_)?prefix\s*=\s*["'](/[\w./-]*)["']"""),  # FastAPI APIRouter / include_router, Flask
    re.compile(r"""\.use\(\s*["'`](/[\w./-]*)["'`]\s*,"""),  # Express app.use('/api', router)
    re.compile(r"""setGlobalPrefix\(\s*["'`]/?([\w./-]+)["'`]"""),  # NestJS
    re.compile(r"""\.(?:PathPrefix|Route)\(\s*["'`](/[\w./-]*)["'`]"""),  # gorilla/mux, chi
]
CODE = (".go", ".py", ".ts", ".js", ".mjs", ".cjs")


def prefix_candidates(work: Path, limit: int = 12) -> list[str]:
    """Route group prefixes declared in the code (`r.Group("/api/v1")`), and pairs of them (`/api` + `/v1`)."""
    found: list[str] = []
    for f in walk(work, CODE):
        if "test" in f.name or "node_modules" in f.parts:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in _PREFIX:
            for m in pattern.finditer(text):
                p = "/" + m.group(1).strip("/")
                if p != "/" and p not in found:
                    found.append(p)
    pairs = [a + b for a in found for b in found if a != b and not b.startswith(a)]
    return ["", *found[:limit], *pairs[:limit]]


async def discover_prefix(http: httpx.AsyncClient, found: list[Route], candidates: list[str]) -> tuple[str, str]:
    """The prefix under which the app serves its routes: the first candidate where a plain GET route isn't a 404.
    Returns (prefix, how it was found)."""
    probes = [r for r in found if r.method == "GET" and r.plain and r.path != "/"][:4]
    if not probes:
        return "", "no plain GET route to probe"
    for prefix in candidates:
        for r in probes:
            try:
                status = (await http.get(prefix + r.path, timeout=10)).status_code
            except httpx.HTTPError:
                continue
            if status != 404:
                return prefix, f"GET {prefix + r.path} answered {status}"
    return "", "every probe answered 404; routes are used as declared"


async def smoke_journey(http: httpx.AsyncClient, found: list[Route], prefix: str) -> Journey:
    """Every GET without parameters. A route registered outside the prefixed group (`/health` next to `/api/v1`)
    answers 404 under the prefix; it is then called as declared."""
    steps = []
    for r in found:
        if r.method != "GET" or not r.plain or any(w in r.path.lower() for w in ("swagger", "openapi", "/docs")):
            continue
        path = prefix + r.path if prefix and not r.path.startswith(prefix) else r.path
        if path != r.path and await _status(http, path) == 404 and await _status(http, r.path) not in (404, None):
            path = r.path
        steps.append(Step(f"GET {r.path}", "GET", path))
    return Journey("smoke", steps, "smoke", "Every GET without parameters, without logging in")


async def _status(http: httpx.AsyncClient, path: str) -> int | None:
    try:
        return (await http.get(path, timeout=10)).status_code
    except httpx.HTTPError:
        return None


# ── running journeys ────────────────────────────────────────────────────────
class Missing(KeyError):
    pass


def fill(value: Any, variables: dict[str, Any]) -> Any:
    """`{{name}}` → its value. A string that is only a variable keeps the value's type (an int id stays an int)."""
    if isinstance(value, dict):
        return {k: fill(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, variables) for v in value]
    if not isinstance(value, str):
        return value
    whole = VAR.fullmatch(value.strip())
    if whole:
        if whole.group(1) not in variables:
            raise Missing(whole.group(1))
        return variables[whole.group(1)]

    def one(m: re.Match[str]) -> str:
        if m.group(1) not in variables:
            raise Missing(m.group(1))
        return str(variables[m.group(1)])

    return VAR.sub(one, value)


_PART = re.compile(r"\.([\w-]+)|\[(\d+)\]")


def pick(data: Any, path: str) -> Any:
    """A value at `$.a.b[0].c`; raises KeyError when it isn't there."""
    path = path.strip()
    if not path.startswith("$"):
        path = "$." + path
    value = data
    for m in _PART.finditer(path[1:]):
        if m.group(1) is not None:
            if not isinstance(value, dict) or m.group(1) not in value:
                raise KeyError(path)
            value = value[m.group(1)]
        else:
            i = int(m.group(2))
            if not isinstance(value, list) or i >= len(value):
                raise KeyError(path)
            value = value[i]
    return value


def _saved(ex: Exchange, var: str, where: str) -> Any:
    """The value at `where`; else the nearest field with the same last name (`$.data.id` when the answer is
    `{"result": {"id": …}}`); for a token, the first JWT or `*token` field. None when there is nothing."""
    if ex.response is None or ex.response.body.kind != "json":
        return None
    body = ex.response.body.value
    try:
        return pick(body, where)
    except KeyError:
        pass
    last = re.split(r"[.\[]", where.strip("$. "))[-1].rstrip("]") or var
    found = _find(body, lambda k, v: k == last and isinstance(v, str | int) and not isinstance(v, bool))
    if found is None and "token" in var.lower():
        found = _find(body, _token_field)
    return found


def _token_field(key: str, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return ("token" in key.lower() and "refresh" not in key.lower()) or bool(JWT.match(value))


def _find(value: Any, ok: Callable[[str, Any], bool], key: str = "") -> Any:
    """Breadth-first: the shallowest match wins (`data.id` before `data.items[0].id`)."""
    queue: list[tuple[str, Any]] = [(key, value)]
    while queue:
        k, v = queue.pop(0)
        if k and ok(k, v):
            return v
        if isinstance(v, dict):
            queue += list(v.items())
        elif isinstance(v, list):
            queue += [(k, x) for x in v[:3]]
    return None


async def run_journeys(
    journeys: list[Journey],
    base_url: str,
    *,
    recording: Recording,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = 30,
    on_exchange: OnExchange | None = None,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send every step in order and add the exchanges to `recording`. Returns the saved variables."""
    variables = dict(variables or {})
    async with httpx.AsyncClient(base_url=base_url, transport=transport) as http:
        for journey in journeys:
            for step in journey.steps:
                try:
                    request = Request(
                        step.method.upper(),
                        fill(step.path, variables),
                        {k.lower(): str(fill(v, variables)) for k, v in step.headers.items()},
                        Body("json", fill(step.body, variables)) if step.body is not None else Body(),
                    )
                except Missing as e:
                    recording.notes.append(f"{journey.name} / {step.name}: skipped, needs {{{{{e.args[0]}}}}}")
                    continue
                if request.body.kind == "json":
                    request.headers.setdefault("content-type", "application/json")
                ex = Exchange(len(recording.exchanges) + 1, request, None, journey.name, step.name, session=SESSION)
                try:
                    ex.response = await send(http, request, timeout)
                except httpx.HTTPError as e:
                    ex.error = f"{e.__class__.__name__}: {e}"
                recording.exchanges.append(ex)
                if on_exchange is not None:
                    await on_exchange(ex)
                for var, where in step.save.items():
                    value = _saved(ex, var, where)
                    if value is None:
                        recording.notes.append(f"{journey.name} / {step.name}: {where} not in the answer")
                    else:
                        variables[var] = value
    return variables
