"""Conversations API: create, reply, list, search, rename, pin, edit (branch), delete. Uses replies that need no
model call (an unsupported language is declined by rule)."""

from __future__ import annotations

import time
from typing import Any

from .conftest import AppFactory


def settled(client: Any, cid: str) -> dict[str, Any]:
    for _ in range(100):
        detail: dict[str, Any] = client.get(f"/api/conversations/{cid}").json()
        if not detail["busy"] and all(m["status"] != "streaming" for m in detail["messages"]):
            return detail
        time.sleep(0.05)
    raise AssertionError("reply did not finish")


def test_conversation_lifecycle(app_factory: AppFactory) -> None:
    with app_factory() as client:
        res = client.post("/api/conversations", json={"content": "Make a calculator in PHP"})
        assert res.status_code == 201
        cid = res.json()["conversation"]["id"]
        detail = settled(client, cid)
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
        assert detail["messages"][1]["kind"] == "decline"
        assert "PHP isn't supported" in detail["messages"][1]["content"]

        # Edit the first message: a sibling branch, shown instead of the original.
        first = detail["messages"][0]["id"]
        res = client.post(f"/api/conversations/{cid}/messages", json={"content": "Write it in Rust", "edit_of": first})
        assert res.status_code == 201
        detail = settled(client, cid)
        assert detail["messages"][0]["content"] == "Write it in Rust"
        assert len(detail["messages"][0]["siblings"]) == 2
        assert client.post(f"/api/conversations/{cid}/messages/{first}/switch").status_code == 204
        assert settled(client, cid)["messages"][0]["content"] == "Make a calculator in PHP"

        assert client.patch(f"/api/conversations/{cid}", json={"title": "PHP calc", "pinned": True}).json()["pinned"]
        assert [c["title"] for c in client.get("/api/conversations?q=rust").json()] == ["PHP calc"]
        assert client.get("/api/conversations?q=nothing-like-this").json() == []
        assert any(c["command"] == "/review-code" for c in client.get("/api/commands").json())

        assert client.delete(f"/api/conversations/{cid}").status_code == 204
        assert client.get(f"/api/conversations/{cid}").status_code == 404
