"""Replay a recording against a running app and compare every answer (CODEWRIGHT.md Section 5.18).

Requests are sent again in order, one cookie jar per journey. Values the app handed out earlier (an ID, a token, a
`Location`) differ on a new run, so the replay **links** them: when a recorded answer and the new answer differ in
such a value, later requests get the new value in place of the recorded one, and the difference itself is noise.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from agent.verification.diff import Comparer, Difference, Intent, value_key
from agent.verification.noise import HTTP_DATE, ID_KEY, ISO_TIME, JWT, NoiseRules
from agent.verification.traffic import Body, Exchange, Recording, Request, Response, request_headers

MIN_LINK = 6  # shorter strings ("ok", "USD") are values, not identifiers
MIN_SUBSTRING = 12  # only long values are replaced inside other text ("Bearer <token>")
OnExchange = Callable[[dict[str, Any]], Awaitable[None]]
OnSent = Callable[[Request, Response | None], Awaitable[None]]  # the request as sent (after linking) and its answer


async def send(http: httpx.AsyncClient, request: Request, timeout: float = 30) -> Response:
    """One request as recorded (no redirects followed: a `Location` is part of the answer)."""
    headers = request_headers(request.headers)
    started = time.monotonic()
    response = await http.request(
        request.method, request.path, headers=headers, content=request.body.to_bytes(), timeout=timeout,
        follow_redirects=False,
    )  # fmt: skip
    return Response(
        response.status_code,
        {k.lower(): v for k, v in response.headers.items()},
        Body.from_bytes(response.content, response.headers.get("content-type", "")),
        round((time.monotonic() - started) * 1000, 1),
    )


# ── linking values handed out by the app ────────────────────────────────────
class Linker:
    def __init__(self) -> None:
        self.linked: dict[str, Any] = {}  # value_key(recorded value) → the new run's value

    def learn(self, before: Response | None, after: Response | None) -> None:
        if before is None or after is None:
            return
        if before.body.kind == "json" and after.body.kind == "json":
            self._walk("", before.body.value, after.body.value)
        a, b = before.headers.get("location", ""), after.headers.get("location", "")
        for x, y in zip(urlsplit(a).path.split("/"), urlsplit(b).path.split("/"), strict=False):
            if x != y and len(x) >= MIN_LINK:
                self.linked[f"str:{x}"] = y

    def _walk(self, key: str, a: Any, b: Any) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            for k in a.keys() & b.keys():
                self._walk(k, a[k], b[k])
        elif isinstance(a, list) and isinstance(b, list):
            for x, y in zip(a, b, strict=False):
                self._walk(key, x, y)
        elif a != b and _linkable(key, a) and type(a) is type(b):
            k = value_key(a)
            if k is not None:
                self.linked[k] = b

    def apply(self, request: Request) -> Request:
        if not self.linked:
            return request
        url = urlsplit(request.path)
        path = "/".join(self._segment(s) for s in url.path.split("/"))
        query = urlencode([(k, self._text(v, exact=True)) for k, v in parse_qsl(url.query, keep_blank_values=True)])
        headers = {k: self._text(v) for k, v in request.headers.items()}
        body = request.body
        if body.kind == "json":
            body = Body("json", self._value(body.value))
        elif body.kind == "text":
            body = Body("text", self._text(str(body.value)))
        return Request(request.method, path + (f"?{query}" if query else ""), headers, body)

    def _segment(self, segment: str) -> str:
        for k in (f"str:{segment}", f"int:{segment}"):
            if k in self.linked:
                return str(self.linked[k])
        return segment

    def _text(self, text: str, exact: bool = False) -> str:
        if f"str:{text}" in self.linked:
            return str(self.linked[f"str:{text}"])
        if exact:
            return self._segment(text)
        for k, new in self.linked.items():
            old = k.split(":", 1)[1]
            if k.startswith("str:") and len(old) >= MIN_SUBSTRING and old in text:
                text = text.replace(old, str(new))
        return text

    def _value(self, value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {k: self._value(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self._value(v, key) for v in value]
        if isinstance(value, str):
            return self._text(value)
        k = value_key(value)
        if k is not None and k in self.linked and _linkable(key, value):
            return self.linked[k]
        return value


def _linkable(key: str, value: Any) -> bool:
    """Values an app hands out and a client sends back: IDs and tokens, not names or amounts."""
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, int):
        return bool(ID_KEY.search(key))
    if isinstance(value, str):
        if JWT.match(value):
            return True
        if ISO_TIME.match(value) or HTTP_DATE.match(value):
            return False  # a time is compared by the timestamp rule, never sent back as an ID
        return len(value) >= MIN_LINK and " " not in value and (bool(ID_KEY.search(key)) or _random_looking(value))
    return False


def _random_looking(value: str) -> bool:
    """`3f1c…`, `AbC123xyz…`: letters and digits mixed, the shape of a generated value."""
    digits = sum(c.isdigit() for c in value)
    return digits >= 2 and any(c.isalpha() for c in value) and len(value) >= 10


# ── the replay ──────────────────────────────────────────────────────────────
@dataclass
class ExchangeResult:
    seq: int
    journey: str
    step: str
    method: str
    path: str  # as sent (after linking)
    status_before: int | None
    status_after: int | None
    duration_before_ms: float = 0
    duration_after_ms: float = 0
    differences: list[Difference] = field(default_factory=list)
    error: str = ""

    @property
    def regressions(self) -> int:
        return sum(1 for d in self.differences if d.verdict == "regression")

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "differences": [d.as_dict() for d in self.differences], "regressions": self.regressions}


@dataclass
class ReplayReport:
    id: str
    recording: str
    base_url: str
    started_at: float
    duration_s: float = 0
    results: list[ExchangeResult] = field(default_factory=list)
    rules: list[dict[str, Any]] = field(default_factory=list)
    intents: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"exchanges": len(self.results), "regression": 0, "noise": 0, "intended": 0, "identical": 0}
        for r in self.results:
            if not r.differences:
                out["identical"] += 1
            for d in r.differences:
                out[d.verdict] += 1
        return out

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(r.regressions == 0 for r in self.results)

    def noise_used(self) -> dict[str, int]:
        used: dict[str, int] = {}
        for r in self.results:
            for d in r.differences:
                if d.verdict == "noise" and d.rule:
                    used[d.rule] = used.get(d.rule, 0) + 1
        return used

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": "replay",
            "recording": self.recording,
            "base_url": self.base_url,
            "started_at": self.started_at,
            "duration_s": self.duration_s,
            "ok": self.ok,
            "counts": self.counts(),
            "noise_used": self.noise_used(),
            "results": [r.as_dict() for r in self.results],
            "rules": self.rules,
            "intents": self.intents,
            "notes": self.notes,
        }


async def replay(  # noqa: PLR0913  (the recording, where, and optional hooks)
    recording: Recording,
    base_url: str,
    rules: NoiseRules,
    *,
    report_id: str,
    intents: list[Intent] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = 30,
    on_exchange: OnExchange | None = None,
    on_sent: OnSent | None = None,
) -> ReplayReport:
    report = ReplayReport(report_id, recording.id, base_url, time.time(), rules=rules.as_list(),
                          intents=[asdict(i) for i in intents or []])  # fmt: skip
    linker = Linker()
    comparer = Comparer(rules, linker.linked, intents)
    clients: dict[str, httpx.AsyncClient] = {}
    started = time.monotonic()
    try:
        for ex in sorted(recording.exchanges, key=lambda e: e.seq):
            jar = ex.session or ex.journey
            http = clients.get(jar)
            if http is None:
                http = clients[jar] = httpx.AsyncClient(base_url=base_url, transport=transport)
            result = await _one(http, ex, linker, comparer, timeout, on_sent)
            report.results.append(result)
            if on_exchange is not None:
                await on_exchange(result.as_dict())
    finally:
        for c in clients.values():
            await c.aclose()
    report.duration_s = round(time.monotonic() - started, 2)
    return report


async def _one(
    http: httpx.AsyncClient, ex: Exchange, linker: Linker, comparer: Comparer, timeout: float, on_sent: OnSent | None
) -> ExchangeResult:
    request = linker.apply(ex.request)
    result = ExchangeResult(
        ex.seq, ex.journey, ex.step, request.method, request.path, ex.response.status if ex.response else None, None,
        ex.response.duration_ms if ex.response else 0,
    )  # fmt: skip
    if ex.request.body.kind == "binary":
        result.error = "skipped: the recorded request had a binary body, which isn't kept"
        return result
    try:
        live: Response | None = await send(http, request, timeout)
    except httpx.HTTPError as e:
        live, result.error = None, f"{e.__class__.__name__}: {e}"
    if live is not None:
        result.status_after, result.duration_after_ms = live.status, live.duration_ms
    if on_sent is not None:
        await on_sent(request, live)
    linker.learn(ex.response, live)
    result.differences = comparer.compare(ex.endpoint, ex.response, live)
    return result
