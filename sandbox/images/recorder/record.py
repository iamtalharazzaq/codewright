"""mitmproxy addon for the Codewright recorder (CODEWRIGHT.md Phase 7): every request that passes through the
reverse proxy is appended to a JSON-lines file in the workspace, which Codewright reads as a recording.

Bodies are kept as base64 with their content type; Codewright decides what is JSON, text or binary.
"""

from __future__ import annotations

import base64
import json
import os
import time

from mitmproxy import ctx, http

LIMIT = 1_000_000  # bytes of a body kept


class Recorder:
    def __init__(self) -> None:
        self.seq = 0

    def load(self, loader) -> None:  # type: ignore[no-untyped-def]
        loader.add_option("record_file", str, "/work/.codewright/traffic/recording.jsonl", "where to append")

    def response(self, flow: http.HTTPFlow) -> None:
        if flow.response is None:
            return
        self.seq += 1
        req, res = flow.request, flow.response
        entry = {
            "seq": self.seq,
            "at": time.time(),
            "client": flow.client_conn.peername[0] if flow.client_conn.peername else "",
            "request": {
                "method": req.method,
                "path": req.path,
                "headers": dict(req.headers.items()),
                "body": base64.b64encode((req.raw_content or b"")[:LIMIT]).decode(),
            },
            "response": {
                "status": res.status_code,
                "headers": dict(res.headers.items()),
                "body": base64.b64encode((res.content or b"")[:LIMIT]).decode(),
                "duration_ms": round(((res.timestamp_end or 0) - (req.timestamp_start or 0)) * 1000, 1),
            },
        }
        path = ctx.options.record_file
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


addons = [Recorder()]
