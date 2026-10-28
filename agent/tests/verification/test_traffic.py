"""Exchanges, recordings, HAR import and the static/HTML filter (CODEWRIGHT.md Phase 7 task 3)."""

from __future__ import annotations

import json
from pathlib import Path

from agent.verification.traffic import (
    Body,
    Exchange,
    Recording,
    Request,
    Response,
    exchange_from_dict,
    from_har,
    is_api_call,
    load,
    request_headers,
    save,
)


def test_body_round_trips_json() -> None:
    body = Body.from_bytes(b'{"a": 1}', "application/json; charset=utf-8")
    assert body.kind == "json" and body.value == {"a": 1}
    assert json.loads(body.to_bytes() or b"{}") == {"a": 1}


def test_body_binary_is_not_json() -> None:
    body = Body.from_bytes(b"\x89PNG\r\n", "image/png")
    assert body.kind == "binary"


def test_request_headers_drops_hop_by_hop_and_cookies() -> None:
    kept = request_headers({"Host": "x", "Cookie": "a=b", "Content-Length": "3", "Authorization": "Bearer t"})
    assert kept == {"authorization": "Bearer t"}


def test_recording_save_and_load_round_trips(tmp_path: Path) -> None:
    ex = Exchange(
        1, Request("GET", "/api/x", {}, Body()), Response(200, {}, Body.from_bytes(b"{}", "application/json"), 1.0)
    )
    recording = Recording(Recording.new_id(), "journeys", {"component": "api"}, [ex])
    path = save(recording, tmp_path / "recordings")
    back = load(path)
    assert back.id == recording.id
    assert back.exchanges[0].request.path == "/api/x"
    assert back.exchanges[0].response is not None and back.exchanges[0].response.status == 200


def test_recording_summary_counts_server_errors_and_unanswered() -> None:
    ok = Exchange(1, Request("GET", "/a", {}, Body()), Response(200, {}, Body(), 1.0), journey="j")
    broke = Exchange(2, Request("GET", "/b", {}, Body()), Response(500, {}, Body(), 1.0), journey="j")
    gone = Exchange(3, Request("GET", "/c", {}, Body()), None, journey="j", error="connection refused")
    summary = Recording(Recording.new_id(), "journeys", {}, [ok, broke, gone]).summary()
    assert summary["exchanges"] == 3
    assert summary["server_errors"] == 1
    assert summary["unanswered"] == 1


def test_exchange_from_dict_roundtrip() -> None:
    ex = Exchange(1, Request("POST", "/a", {}, Body.from_bytes(b'{"x":1}', "application/json")),
                  Response(201, {}, Body(), 2.0), journey="j", step="s")  # fmt: skip
    back = exchange_from_dict(
        json.loads(
            json.dumps(
                {
                    "seq": ex.seq,
                    "journey": ex.journey,
                    "step": ex.step,
                    "error": ex.error,
                    "session": ex.session,
                    "request": {
                        "method": ex.request.method,
                        "path": ex.request.path,
                        "headers": ex.request.headers,
                        "body": {"kind": "json", "value": {"x": 1}},
                    },
                    "response": {
                        "status": 201,
                        "headers": {},
                        "duration_ms": 2.0,
                        "body": {"kind": "none", "value": None},
                    },
                }
            )
        )
    )
    assert back.request.body.value == {"x": 1}
    assert back.response is not None and back.response.status == 201


def test_from_har_keeps_only_matching_entries() -> None:
    har = {
        "log": {
            "entries": [
                {
                    "request": {"method": "GET", "url": "https://x/api/a", "headers": []},
                    "response": {
                        "status": 200,
                        "headers": [{"name": "content-type", "value": "application/json"}],
                        "content": {"text": "{}", "mimeType": "application/json"},
                    },
                    "time": 5,
                },
                {
                    "request": {"method": "GET", "url": "https://x/app.js", "headers": []},
                    "response": {"status": 200, "headers": [], "content": {}},
                    "time": 1,
                },
            ]
        }
    }
    kept = from_har(har, keep=is_api_call)
    assert [e.request.path for e in kept] == ["/api/a"]


def test_is_api_call_excludes_html_and_static() -> None:
    html = Exchange(1, Request("GET", "/", {}, Body()),
                    Response(200, {"content-type": "text/html"}, Body(), 1.0))  # fmt: skip
    asset = Exchange(2, Request("GET", "/app.js", {}, Body()), Response(200, {}, Body(), 1.0))
    api = Exchange(3, Request("GET", "/api/items", {}, Body()),
                   Response(200, {"content-type": "application/json"}, Body(), 1.0))  # fmt: skip
    write = Exchange(4, Request("POST", "/api/items", {}, Body()), Response(201, {}, Body(), 1.0))
    assert not is_api_call(html)
    assert not is_api_call(asset)
    assert is_api_call(api)
    assert is_api_call(write)
