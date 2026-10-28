"""Replay (CODEWRIGHT.md Section 5.18): the Linker learns IDs and tokens handed out by the app and rewrites later
requests, and `replay()` end to end against a fake transport gives 0 regressions when the app answers identically
except for a fresh ID."""

from __future__ import annotations

import json

import httpx

from agent.verification.noise import NoiseRules
from agent.verification.replay import Linker, replay
from agent.verification.traffic import Body, Exchange, Recording, Request, Response


def test_linker_learns_an_id_and_rewrites_the_path() -> None:
    linker = Linker()
    before = Response(201, {}, Body("json", {"id": "old-id-123"}), 1.0)
    after = Response(201, {}, Body("json", {"id": "new-id-456"}), 1.0)
    linker.learn(before, after)
    rewritten = linker.apply(Request("GET", "/api/items/old-id-123", {}, Body()))
    assert rewritten.path == "/api/items/new-id-456"


def test_linker_rewrites_a_token_inside_a_header() -> None:
    linker = Linker()
    before = Response(200, {}, Body("json", {"token": "aaaa1111bbbb2222cccc"}), 1.0)
    after = Response(200, {}, Body("json", {"token": "dddd3333eeee4444ffff"}), 1.0)
    linker.learn(before, after)
    rewritten = linker.apply(Request("GET", "/api/me", {"Authorization": "Bearer aaaa1111bbbb2222cccc"}, Body()))
    assert rewritten.headers["Authorization"] == "Bearer dddd3333eeee4444ffff"


def test_linker_leaves_short_or_name_values_alone() -> None:
    linker = Linker()
    before = Response(200, {}, Body("json", {"status": "ok", "amount": 19.99}), 1.0)
    after = Response(200, {}, Body("json", {"status": "ok", "amount": 19.99}), 1.0)
    linker.learn(before, after)
    assert linker.linked == {}


def test_linker_does_not_link_timestamps() -> None:
    linker = Linker()
    before = Response(200, {}, Body("json", {"created_at": "2024-01-01T00:00:00Z"}), 1.0)
    after = Response(200, {}, Body("json", {"created_at": "2024-06-01T00:00:00Z"}), 1.0)
    linker.learn(before, after)
    assert linker.linked == {}


async def test_replay_gives_zero_regressions_when_only_the_id_is_fresh() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "new-item-42", "name": "widget"})

    exchange = Exchange(
        1,
        Request("GET", "/api/items/old-item-1", {}, Body()),
        Response(200, {"content-type": "application/json"}, Body("json", {"id": "old-item-1", "name": "widget"}), 1.0),
        journey="j1",
        step="get item",
    )
    recording = Recording(Recording.new_id(), "journeys", {}, [exchange])
    report = await replay(recording, "http://app", NoiseRules(), report_id="t1", transport=httpx.MockTransport(handler))
    assert report.ok
    assert report.counts()["regression"] == 0
    assert report.results[0].differences[0].verdict == "noise"


async def test_replay_flags_a_real_change_as_a_regression() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "item-x", "name": "renamed"})

    exchange = Exchange(
        1, Request("GET", "/api/items/item-x", {}, Body()),
        Response(200, {"content-type": "application/json"}, Body("json", {"id": "item-x", "name": "widget"}), 1.0),
        journey="j1", step="get item",
    )  # fmt: skip
    recording = Recording(Recording.new_id(), "journeys", {}, [exchange])
    report = await replay(recording, "http://app", NoiseRules(), report_id="t2", transport=httpx.MockTransport(handler))
    assert not report.ok
    assert report.counts()["regression"] == 1


async def test_replay_on_sent_sees_the_linked_request() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"id": "new-item-1"})

    exchange = Exchange(
        1, Request("GET", "/api/items/old-item-1", {}, Body()),
        Response(200, {"content-type": "application/json"}, Body("json", {"id": "old-item-1"}), 1.0),
        journey="j1", step="get item",
    )  # fmt: skip
    recording = Recording(Recording.new_id(), "journeys", {}, [exchange])

    async def on_sent(request: Request, live: Response | None) -> None:
        assert live is not None
        assert json.loads(live.body.to_bytes() or b"{}")["id"] == "new-item-1"

    await replay(
        recording, "http://app", NoiseRules(), report_id="t3", transport=httpx.MockTransport(handler), on_sent=on_sent
    )
    assert seen == ["/api/items/old-item-1"]  # the first request still carries the recorded id: nothing to link yet
