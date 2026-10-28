"""Google Drive as MCP tools: the server, the chat's in-process client, and the HTTP token gate."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from codewright_api import drive_mcp
from codewright_api.settings import Settings
from connectors import drive
from connectors.drive import DriveToolError

DRIVE_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz"


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch) -> drive_mcp.DriveAgent:
    async def token(*_: Any) -> str:
        return "tok"

    async def search(tok: str | None, query: str, limit: int = 10) -> list[dict[str, str]]:
        assert tok == "tok"
        return [{"id": DRIVE_ID, "name": f"About {query}", "type": "text/plain", "link": "https://x/1", "modified": ""}]

    async def read_text(tok: str | None, fid: str) -> dict[str, Any]:
        if fid.startswith("gone"):
            raise DriveToolError("No such file.")
        return {"id": fid, "name": "Spec", "type": "text/plain", "text": "the spec text", "truncated": False}

    monkeypatch.setattr(drive_mcp, "drive_access_token", token)
    monkeypatch.setattr(drive, "search", search)
    monkeypatch.setattr(drive, "read_text", read_text)
    return drive_mcp.DriveAgent(drive_mcp.build_server(None, Settings()))  # type: ignore[arg-type]


async def test_the_server_offers_three_drive_tools(agent: drive_mcp.DriveAgent) -> None:
    from mcp.client import Client  # noqa: PLC0415

    async with Client(agent.server) as client:
        names = sorted(t.name for t in (await client.list_tools()).tools)
    assert names == ["drive_read", "drive_search", "drive_write"]


async def test_a_drive_link_in_a_message_is_read_through_the_tools(agent: drive_mcp.DriveAgent) -> None:
    link = f"https://docs.google.com/document/d/{DRIVE_ID}/edit"
    text = await agent.context_for(f"Summarize {link} for me")
    assert "Google Drive file 'Spec'" in text and "the spec text" in text


async def test_asking_to_search_drive_runs_a_search(agent: drive_mcp.DriveAgent) -> None:
    text = await agent.context_for("Please search my Google Drive for the launch plan")
    assert "Google Drive search results" in text and "About launch plan" in text and "https://x/1" in text


async def test_other_messages_and_drive_errors_do_not_break_the_chat(agent: drive_mcp.DriveAgent) -> None:
    assert await agent.context_for("How does checkout work?") == ""
    ok, out = await agent.call("drive_read", {"file": "short"})
    assert ok is False and "Drive link or a file id" in out
    ok, out = await agent.call("drive_read", {"file": "gone" * 6})  # Drive says no such file
    assert ok is False and out.endswith("No such file.")


def test_file_ids_come_from_links_or_bare_ids() -> None:
    assert drive_mcp.file_id(f"https://drive.google.com/file/d/{DRIVE_ID}/view") == DRIVE_ID
    assert drive_mcp.file_id(f"https://drive.google.com/open?id={DRIVE_ID}") == DRIVE_ID
    assert drive_mcp.file_id(DRIVE_ID) == DRIVE_ID
    with pytest.raises(ToolError):
        drive_mcp.file_id("short")


def _gated(token: str) -> TestClient:
    async def hello(_: Any) -> PlainTextResponse:
        return PlainTextResponse("tools")

    return TestClient(drive_mcp.BearerGate(Starlette(routes=[Route("/", hello)]), token))


def test_the_http_endpoint_is_off_without_a_token_and_needs_it_with_one() -> None:
    assert _gated("").get("/").status_code == 404
    assert _gated("s3cret").get("/").status_code == 401
    assert _gated("s3cret").get("/", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert _gated("s3cret").get("/", headers={"Authorization": "Bearer s3cret"}).text == "tools"


def test_the_app_serves_the_drive_endpoint_only_with_a_token(client: TestClient) -> None:
    assert client.post("/mcp/drive/", json={}).status_code == 404  # MCP_TOKEN is not set in tests
    assert SecretStr("x").get_secret_value() == "x"
