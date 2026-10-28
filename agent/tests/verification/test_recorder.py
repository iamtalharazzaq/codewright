"""The traffic recorder (CODEWRIGHT.md Phase 7 task 3): its command line, and reading mitmproxy's JSON-lines file
back into exchanges (dropping static assets)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from agent.verification.recorder import command, read


def test_command_names_the_app_port_and_record_file() -> None:
    cmd = command(8080, "a/b.jsonl", port=18080)
    assert "reverse:http://127.0.0.1:8080" in cmd
    assert "--set" in cmd and "record_file=/work/a/b.jsonl" in cmd


def test_read_keeps_api_calls_and_drops_static_assets(tmp_path: Path) -> None:
    def entry(method: str, path: str, status: int, ctype: str) -> dict[str, object]:
        return {
            "client": "127.0.0.1",
            "request": {"method": method, "path": path, "headers": {}, "body": ""},
            "response": {"status": status, "headers": {"content-type": ctype}, "body": base64.b64encode(b"{}").decode(),
                        "duration_ms": 5},
        }  # fmt: skip

    path = tmp_path / "recording.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(e)
            for e in [
                entry("GET", "/api/items", 200, "application/json"),
                entry("GET", "/app.js", 200, "application/javascript"),
            ]
        ),
        encoding="utf-8",
    )
    exchanges = read(path)
    assert [e.request.path for e in exchanges] == ["/api/items"]
    assert exchanges[0].seq == 1


def test_read_missing_file_gives_nothing(tmp_path: Path) -> None:
    assert read(tmp_path / "missing.jsonl") == []
