"""The traffic recorder (CODEWRIGHT.md Phase 7 task 3): mitmproxy as a reverse proxy in front of a running app, in
the sandbox. The user browses the app through it; every exchange goes to a JSON-lines file in the workspace
(`sandbox/images/recorder/record.py`), which becomes a `Recording` when the recorder stops.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from agent.verification.traffic import Body, Exchange, Request, Response, is_api_call, request_headers

PORT = 18_080  # inside the app's network namespace (shared with the app's preview)
FILE = ".codewright/traffic/recording.jsonl"


def command(app_port: int, file: str = FILE, port: int = PORT) -> list[str]:
    return [
        "mitmdump", "--mode", f"reverse:http://127.0.0.1:{app_port}", "--listen-host", "0.0.0.0",  # noqa: S104  (the gateway reaches it)
        "--listen-port", str(port), "-s", "/opt/codewright/record.py", "--set", f"record_file=/work/{file}",
        "--set", "termlog_verbosity=warn", "--set", "flow_detail=0",
    ]  # fmt: skip


def read(path: Path, *, everything: bool = False) -> list[Exchange]:
    """The recorder's file → exchanges. Static assets and HTML pages are left out unless `everything`."""
    out: list[Exchange] = []
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry: dict[str, Any] = json.loads(line)
        except ValueError:
            continue
        req, res = entry["request"], entry["response"]
        rh = {k.lower(): v for k, v in req.get("headers", {}).items()}
        sh = {k.lower(): v for k, v in res.get("headers", {}).items()}
        ex = Exchange(
            len(out) + 1,
            Request(req["method"], req["path"], request_headers(rh),
                    Body.from_bytes(base64.b64decode(req.get("body", "")), rh.get("content-type", ""))),
            Response(int(res["status"]), sh, Body.from_bytes(base64.b64decode(res.get("body", "")),
                     sh.get("content-type", "")), float(res.get("duration_ms", 0))),
            journey="browser",
            step=f"{req['method']} {req['path']}"[:120],
            session=str(entry.get("client") or "browser"),
        )  # fmt: skip
        if everything or is_api_call(ex):
            out.append(ex)
    for i, ex in enumerate(out, 1):
        ex.seq = i
    return out
