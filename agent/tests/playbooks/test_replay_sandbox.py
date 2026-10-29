"""Verification engine (CODEWRIGHT.md Phase 7): a recorded exchange replayed against a really running app in the
real sandbox runner. A tiny Python HTTP app runs as a sandbox preview; the replay (`agent.verification.replay`) sends
the recording's request to the preview's published port and compares the answer. Unchanged app: 0 regressions.
Changed app (same route, different answer): a regression.

Needs the host's loopback: a preview's port is published on the Docker host's `127.0.0.1` only (the gateway's
isolation, deliberately left as it is), so this test is skipped inside the checks container and runs with
`make check-sandbox-host` (the checks image on the host network). The recorder (mitmproxy) is not covered; the
recording is built by hand, like the engine's own unit tests do. See PROGRESS.md's Retrofit section, Phase 7.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
import pytest

from agent.tests.sandbox_harness import start_session
from agent.tools.sandbox import SandboxClient
from agent.verification.noise import NoiseRules
from agent.verification.replay import replay
from agent.verification.traffic import Body, Exchange, Recording, Request, Response

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(
        os.environ.get("SANDBOX_TESTS") != "1" or os.environ.get("SANDBOX_HOST_LOOPBACK") != "1",
        reason="needs the host's 127.0.0.1 for preview ports: make check-sandbox-host",
    ),
]

SERVER = (
    "import json\nfrom http.server import BaseHTTPRequestHandler, HTTPServer\n\n\n"
    "class H(BaseHTTPRequestHandler):\n    def do_GET(self):\n        body = json.dumps({'items': %s}).encode()\n"
    "        self.send_response(200)\n        self.send_header('Content-Type', 'application/json')\n"
    "        self.send_header('Content-Length', str(len(body)))\n        self.end_headers()\n"
    "        self.wfile.write(body)\n\n"
    "    def log_message(self, *a):\n        pass\n\n\nHTTPServer(('0.0.0.0', 8000), H).serve_forever()\n"
)
RECORDING = Recording(
    "rec-test",
    "journeys",
    {"port": 8000},
    [
        Exchange(
            1,
            Request("GET", "/api/items"),
            Response(200, {"content-type": "application/json"}, Body("json", {"items": [1, 2]})),
            journey="items",
            step="GET /api/items",
        )
    ],
)


async def _serve(client: SandboxClient, sid: str, work: Path, items: str) -> tuple[str, str]:
    (work / "server.py").write_text(SERVER % items, encoding="utf-8")
    preview = await client.start_preview(
        sid, {"kind": "web", "toolchain": "python", "cmd": ["python3", "server.py"], "workdir": ".", "port": 8000}
    )
    url = preview["url"]
    async with httpx.AsyncClient() as http:
        for _ in range(60):
            try:
                if (await http.get(url + "api/items", timeout=2)).status_code == 200:
                    return preview["id"], url.rstrip("/")
            except httpx.HTTPError:
                await asyncio.sleep(0.5)
    raise AssertionError(f"the preview never answered at {url}: {await client.preview(sid, preview['id'])}")


async def test_a_recorded_exchange_replays_clean_on_the_same_app_and_flags_a_changed_answer(
    workspace: tuple[SandboxClient, str, Path],
) -> None:
    client, ws, work = workspace
    sid = await start_session(client, ws, work)
    try:
        pid, url = await _serve(client, sid, work, "[1, 2]")
        same = await replay(RECORDING, url, NoiseRules(), report_id="same")
        assert same.ok and same.counts()["regression"] == 0 and same.counts()["exchanges"] == 1, same.as_dict()
        await client.stop_preview(sid, pid)

        pid, url = await _serve(client, sid, work, "[1, 2, 3]")
        changed = await replay(RECORDING, url, NoiseRules(), report_id="changed")
        assert not changed.ok and changed.counts()["regression"] >= 1, changed.as_dict()
    finally:
        await client.delete_session(sid)
