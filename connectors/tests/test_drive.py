"""Drive search/read/write (`connectors.drive`) against a faked Google API."""

from __future__ import annotations

import httpx
import pytest

from connectors import drive
from connectors.drive import DriveToolError

DOC = {"id": "doc1", "name": "Spec", "mimeType": "application/vnd.google-apps.document"}


def _api(routes: dict[str, httpx.Response], seen: list[httpx.Request] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        key = request.url.path + ("?alt=media" if request.url.params.get("alt") == "media" else "")
        return routes.get(key, httpx.Response(404, text="no route " + key))

    return httpx.MockTransport(handler)


async def test_search_asks_for_matching_untrashed_files_and_trims_the_answer() -> None:
    seen: list[httpx.Request] = []
    files = {"files": [{"id": "a", "name": "Spec", "mimeType": "text/plain", "webViewLink": "https://x/a"}]}
    transport = _api({"/drive/v3/files": httpx.Response(200, json=files)}, seen)
    found = await drive.search("tok", "it's a spec", limit=99, transport=transport)
    assert found == [{"id": "a", "name": "Spec", "type": "text/plain", "link": "https://x/a", "modified": ""}]
    params = seen[0].url.params
    assert params["q"] == "fullText contains 'it\\'s a spec' and trashed = false" and params["pageSize"] == "25"
    assert seen[0].headers["authorization"] == "Bearer tok"


async def test_a_google_doc_is_exported_as_text_and_long_text_is_cut() -> None:
    transport = _api(
        {
            "/drive/v3/files/doc1": httpx.Response(200, json=DOC),
            "/drive/v3/files/doc1/export": httpx.Response(200, text="x" * 50),
        }
    )
    out = await drive.read_text("tok", "doc1", max_chars=10, transport=transport)
    assert out["text"] == "x" * 10 and out["truncated"] is True and out["characters"] == 50 and out["name"] == "Spec"


async def test_a_text_file_is_downloaded_and_a_binary_one_is_refused() -> None:
    plain = {"id": "t", "name": "n.md", "mimeType": "text/markdown"}
    png = {"id": "p", "name": "i.png", "mimeType": "image/png"}
    transport = _api(
        {
            "/drive/v3/files/t": httpx.Response(200, json=plain),
            "/drive/v3/files/t?alt=media": httpx.Response(200, text="# hi"),
            "/drive/v3/files/p": httpx.Response(200, json=png),
        }
    )
    assert (await drive.read_text("tok", "t", transport=transport))["text"] == "# hi"
    with pytest.raises(DriveToolError, match="image/png, not a text file"):
        await drive.read_text("tok", "p", transport=transport)


async def test_problems_are_said_in_plain_words() -> None:
    with pytest.raises(DriveToolError, match="isn't connected"):
        await drive.search(None, "x")
    with pytest.raises(DriveToolError, match="isn't shared"):
        await drive.read_text("tok", "missing", transport=_api({}))


async def test_write_creates_a_plain_text_file_in_the_folder() -> None:
    seen: list[httpx.Request] = []
    reply = httpx.Response(200, json={"id": "n1", "name": "notes.txt", "webViewLink": "https://x/n1"})
    transport = _api({"/upload/drive/v3/files": reply}, seen)
    out = await drive.write_text("tok", "notes.txt", "hello", folder_id="F", transport=transport)
    assert out == {"id": "n1", "name": "notes.txt", "link": "https://x/n1"}
    body = seen[0].content.decode()
    assert '"parents": ["F"]' in body and "hello" in body and seen[0].url.params["uploadType"] == "multipart"
