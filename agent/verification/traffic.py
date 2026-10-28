"""Recorded HTTP traffic (CODEWRIGHT.md Phase 7): what was sent to an app and what it answered.

One shape for every source: journeys Codewright sends itself, traffic recorded by the mitmproxy recorder in the
sandbox, and HAR files. A recording is plain JSON, so the user can read it and a later run can replay it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

BodyKind = Literal["none", "json", "text", "binary"]
MAX_TEXT = 200_000  # characters of a text body kept; longer ones keep a hash of the rest
# Not part of a request's meaning: set by the client or the connection, or replaced on replay (the cookie jar).
DROP_REQUEST_HEADERS = {
    "host", "content-length", "connection", "keep-alive", "transfer-encoding", "accept-encoding", "cookie",
    "upgrade", "te", "proxy-connection", "proxy-authorization",
}  # fmt: skip


@dataclass
class Body:
    kind: BodyKind = "none"
    value: Any = None  # parsed JSON, text, or for binary {"sha256", "size"}

    @classmethod
    def from_bytes(cls, data: bytes | None, content_type: str = "") -> Body:
        if not data:
            return cls()
        ctype = content_type.split(";", maxsplit=1)[0].strip().lower()
        if "json" in ctype or (not ctype and data[:1] in (b"{", b"[")):
            try:
                return cls("json", json.loads(data))
            except ValueError:
                pass
        if ctype.startswith("text/") or "json" in ctype or "xml" in ctype or "javascript" in ctype or "form" in ctype:
            text = data.decode("utf-8", errors="replace")
            if len(text) > MAX_TEXT:
                text = text[:MAX_TEXT] + f"\n[cut; sha256 of the whole body {hashlib.sha256(data).hexdigest()}]"
            return cls("text", text)
        try:
            return cls("text", data.decode("utf-8")) if len(data) <= MAX_TEXT else cls._binary(data)
        except UnicodeDecodeError:
            return cls._binary(data)

    @classmethod
    def _binary(cls, data: bytes) -> Body:
        return cls("binary", {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})

    def to_bytes(self) -> bytes | None:
        if self.kind == "json":
            return json.dumps(self.value).encode()
        if self.kind == "text":
            return str(self.value).encode()
        return None  # a binary body isn't kept, so it can't be sent again


@dataclass
class Request:
    method: str
    path: str  # with the query string: /api/v1/products?page=2
    headers: dict[str, str] = field(default_factory=dict)
    body: Body = field(default_factory=Body)


@dataclass
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: Body = field(default_factory=Body)
    duration_ms: float = 0


@dataclass
class Exchange:
    seq: int
    request: Request
    response: Response | None  # None: no answer (refused, timed out)
    journey: str = ""  # the journey or page it belongs to
    step: str = ""
    error: str = ""
    session: str = ""  # requests that share a cookie jar on replay (one browser, or all of Codewright's journeys)

    @property
    def endpoint(self) -> str:
        return f"{self.request.method} {urlsplit(self.request.path).path}"


@dataclass
class Recording:
    id: str
    source: Literal["journeys", "recorder", "har"]
    target: dict[str, Any]  # component, port, prefix: what was recorded
    exchanges: list[Exchange] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    notes: list[str] = field(default_factory=list)

    @staticmethod
    def new_id(prefix: str = "rec") -> str:
        return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def journeys(self) -> list[str]:
        return list(dict.fromkeys(e.journey for e in self.exchanges))

    def summary(self) -> dict[str, Any]:
        answered = [e for e in self.exchanges if e.response is not None]
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "created_at": self.created_at,
            "exchanges": len(self.exchanges),
            "endpoints": len({e.endpoint for e in self.exchanges}),
            "journeys": self.journeys,
            "server_errors": sum(1 for e in answered if e.response and e.response.status >= 500),
            "unanswered": len(self.exchanges) - len(answered),
            "notes": self.notes,
        }


# ── (de)serialization ───────────────────────────────────────────────────────
def _body(data: dict[str, Any] | None) -> Body:
    data = data or {}
    return Body(data.get("kind", "none"), data.get("value"))


def exchange_from_dict(d: dict[str, Any]) -> Exchange:
    req = d["request"]
    res = d.get("response")
    return Exchange(
        seq=int(d["seq"]),
        request=Request(req["method"], req["path"], dict(req.get("headers") or {}), _body(req.get("body"))),
        response=(
            Response(int(res["status"]), dict(res.get("headers") or {}), _body(res.get("body")),
                     float(res.get("duration_ms", 0)))
            if res else None
        ),
        journey=d.get("journey", ""),
        step=d.get("step", ""),
        error=d.get("error", ""),
        session=d.get("session", ""),
    )  # fmt: skip


def recording_from_dict(d: dict[str, Any]) -> Recording:
    return Recording(
        id=d["id"],
        source=d.get("source", "journeys"),
        target=d.get("target") or {},
        exchanges=[exchange_from_dict(e) for e in d.get("exchanges", [])],
        created_at=float(d.get("created_at", 0)),
        notes=list(d.get("notes") or []),
    )


def save(recording: Recording, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{recording.id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(recording.as_dict(), indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def load(path: Path) -> Recording:
    return recording_from_dict(json.loads(path.read_text(encoding="utf-8")))


def request_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items() if k.lower() not in DROP_REQUEST_HEADERS}


# ── HAR (browsers' and mitmproxy's export format) ────────────────────────────
def from_har(har: dict[str, Any], *, keep: Any = None) -> list[Exchange]:
    """The entries of a HAR file. `keep(exchange) -> bool` drops what isn't the app's API (assets, other hosts)."""
    out: list[Exchange] = []
    for entry in har.get("log", {}).get("entries", []):
        req, res = entry.get("request", {}), entry.get("response", {})
        url = urlsplit(req.get("url", ""))
        path = url.path + (f"?{url.query}" if url.query else "")
        rh = {h["name"]: h["value"] for h in req.get("headers", [])}
        post = req.get("postData") or {}
        body = Body.from_bytes(post.get("text", "").encode(), post.get("mimeType", "")) if post else Body()
        content = res.get("content") or {}
        text = content.get("text") or ""
        raw = base64.b64decode(text) if content.get("encoding") == "base64" else text.encode()
        response = Response(
            int(res.get("status") or 0),
            {h["name"].lower(): h["value"] for h in res.get("headers", [])},
            Body.from_bytes(raw, content.get("mimeType", "")),
            float(entry.get("time") or 0),
        )
        ex = Exchange(len(out) + 1, Request(req.get("method", "GET"), path, request_headers(rh), body), response,
                      journey=url.netloc, session=url.netloc)  # fmt: skip
        if keep is None or keep(ex):
            out.append(ex)
    return out


STATIC = (".js", ".mjs", ".css", ".map", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf")


def is_api_call(ex: Exchange) -> bool:
    """Requests that carry the app's behavior: not static assets, dev-server internals or HTML pages."""
    path = urlsplit(ex.request.path).path
    if path.endswith(STATIC) or "/@vite" in path or "/node_modules/" in path or "/__" in path or "/_next/" in path:
        return False
    if ex.request.method != "GET":
        return True
    ctype = (ex.response.headers.get("content-type", "") if ex.response else "").lower()
    return "html" not in ctype and "javascript" not in ctype and "css" not in ctype
