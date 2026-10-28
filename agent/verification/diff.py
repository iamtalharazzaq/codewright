"""Semantic diff of two answers to the same request (CODEWRIGHT.md Section 5.18): status, selected headers and the
body as JSON (or masked text). Each difference is classified: **regression**, **noise** (a rule explains it) or
**intended** (the change was asked for). A replay is accepted only with 0 regressions.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from agent.verification.noise import COMPARED_HEADERS, NoiseRules, generic, glob
from agent.verification.traffic import Body, Response

Verdict = Literal["regression", "noise", "intended"]
MISSING = "<missing>"
MAX_DIFFS = 50  # per exchange: a changed list of 1,000 items is one problem, not 1,000


@dataclass
class Difference:
    where: str  # status, header:<name>, body
    path: str  # JSON path in the body ($.data[0].id), or "" for status/headers
    before: Any
    after: Any
    verdict: Verdict = "regression"
    rule: str | None = None  # the noise rule or intent that explains it
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Intent:
    """A change the user asked for: differences on this endpoint (and body path) are expected."""

    endpoint: str  # "GET /api/v1/products/*" (fnmatch-style on METHOD /path)
    path: str = "**"  # body path pattern
    reason: str = ""

    def covers(self, endpoint: str, where: str, path: str) -> bool:
        if not re.fullmatch(_endpoint_glob(self.endpoint), endpoint):
            return False
        return where != "body" or self.path in ("**", "*") or bool(glob(self.path).fullmatch(generic(path)))


def _endpoint_glob(pattern: str) -> str:
    return re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")


class Comparer:
    def __init__(
        self, rules: NoiseRules, linked: dict[str, Any] | None = None, intents: list[Intent] | None = None
    ) -> None:
        self.rules = rules
        self.linked = linked if linked is not None else {}  # recorded value → the value the replay got instead
        self.intents = intents or []

    def compare(self, endpoint: str, before: Response | None, after: Response | None) -> list[Difference]:
        if before is None or after is None:
            if before is after:
                return []
            return [self._judge(endpoint, Difference("status", "", _status(before), _status(after)))]
        diffs: list[Difference] = []
        if before.status != after.status:
            diffs.append(Difference("status", "", before.status, after.status))
        for name in COMPARED_HEADERS:  # only headers that carry meaning; the rest change on every answer
            a, b = before.headers.get(name, MISSING), after.headers.get(name, MISSING)
            if a != b and not self.rules.header_ignored(name) and not _same_header(name, a, b, self.linked):
                diffs.append(Difference(f"header:{name}", "", a, b))
        diffs += self._body(before.body, after.body)
        return [self._judge(endpoint, d) for d in diffs[:MAX_DIFFS]]

    # ── body ─────────────────────────────────────────────────────────────────
    def _body(self, a: Body, b: Body) -> list[Difference]:
        if a.kind == "json" and b.kind == "json":
            out: list[Difference] = []
            self._walk("$", a.value, b.value, out)
            return out
        if a.kind != b.kind:
            return [Difference("body", "", f"<{a.kind}>", f"<{b.kind}>", note="the body's type changed")]
        if a.kind == "text":
            x, y = self.rules.mask_text(str(a.value)), self.rules.mask_text(str(b.value))
            if x == y:
                return []
            lines = list(difflib.unified_diff(x.splitlines(), y.splitlines(), lineterm="", n=1))[2:40]
            return [Difference("body", "", _cut(x), _cut(y), note="\n".join(lines))]
        if a.kind == "binary" and a.value != b.value:
            return [Difference("body", "", a.value, b.value, note="binary content changed")]
        return []

    def _walk(self, path: str, a: Any, b: Any, out: list[Difference]) -> None:
        if len(out) >= MAX_DIFFS:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in list(a) + [k for k in b if k not in a]:
                sub = f"{path}.{key}"
                if key not in b:
                    out.append(Difference("body", sub, _cut(a[key]), MISSING, note="field removed"))
                elif key not in a:
                    out.append(Difference("body", sub, MISSING, _cut(b[key]), note="field added"))
                else:
                    self._walk(sub, a[key], b[key], out)
            return
        if isinstance(a, list) and isinstance(b, list):
            rule = self.rules.unordered(path)
            if rule is not None and len(a) == len(b) and _multiset(a) == _multiset(b):
                if a != b:
                    out.append(Difference("body", path, "<order>", "<order>", "noise", rule.id, "same items"))
                return
            for i, (x, y) in enumerate(zip(a, b, strict=False)):
                self._walk(f"{path}[{i}]", x, y, out)
            if len(a) != len(b):
                out.append(Difference("body", path, f"{len(a)} items", f"{len(b)} items", note="list length changed"))
            return
        if a == b and type(a) is type(b):
            return
        out.append(Difference("body", path, _cut(a), _cut(b)))

    # ── verdicts ─────────────────────────────────────────────────────────────
    def _judge(self, endpoint: str, d: Difference) -> Difference:
        if d.verdict == "noise":
            return d
        intent = next((i for i in self.intents if i.covers(endpoint, d.where, d.path)), None)
        if intent is not None:
            d.verdict, d.rule, d.note = "intended", f"intent: {intent.endpoint}", intent.reason or d.note
            return d
        if d.where == "body" and d.path:
            rule = self.rules.explain(d.path, d.before, d.after)
            if rule is not None:
                d.verdict, d.rule = "noise", rule.id
            elif self.rules.enabled("linked-values") and _linked(d.before, d.after, self.linked):
                d.verdict, d.rule = "noise", "linked-values"
        return d


def _linked(a: Any, b: Any, linked: dict[str, Any]) -> bool:
    key = value_key(a)
    return key is not None and key in linked and linked[key] == b


def value_key(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str | int | float):
        return f"{type(value).__name__}:{value}"
    return None


def _same_header(name: str, a: str, b: str, linked: dict[str, Any]) -> bool:
    if name == "content-type":
        return a.split(";", maxsplit=1)[0].strip().lower() == b.split(";", maxsplit=1)[0].strip().lower()
    if name == "location":
        pa, pb = urlsplit(a).path.split("/"), urlsplit(b).path.split("/")
        return len(pa) == len(pb) and all(x == y or _linked_text(x, y, linked) for x, y in zip(pa, pb, strict=True))
    return False


def _linked_text(a: str, b: str, linked: dict[str, Any]) -> bool:
    return any(str(linked.get(k)) == b for k in (f"str:{a}", f"int:{a}") if k in linked)


def _multiset(items: list[Any]) -> list[str]:
    return sorted(json.dumps(i, sort_keys=True, default=str) for i in items)


def _status(r: Response | None) -> Any:
    return r.status if r is not None else "no answer"


def _cut(value: Any, limit: int = 300) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    if isinstance(value, dict | list):
        text = json.dumps(value, default=str)
        return value if len(text) <= limit else text[:limit] + "…"
    return value
