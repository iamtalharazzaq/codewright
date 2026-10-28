"""Google Drive reads and writes for the agent's Drive tools (CODEWRIGHT.md V4, C7): search, read a file as text,
write a text file. Uses the connected account's access token (`gdrive.drive_access_token`); importing and delivering
whole projects stays in `connectors.inputs` / `connectors.outputs`, which stream large ZIPs."""

from __future__ import annotations

import json
from typing import Any

import httpx

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
MAX_READ = 20_000  # characters handed to a model
# Google's own formats have no bytes to download: they are exported to the closest plain text.
EXPORTS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/x-yaml", "application/javascript")


class DriveToolError(Exception):
    """Something the model (or the user) can act on: not connected, not found, not a text file."""


def _headers(token: str | None) -> dict[str, str]:
    if not token:
        raise DriveToolError("Google Drive isn't connected: connect it in Settings.")
    return {"Authorization": f"Bearer {token}"}


def _quote(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


async def search(
    token: str | None, query: str, limit: int = 10, transport: httpx.AsyncBaseTransport | None = None
) -> list[dict[str, str]]:
    """Files whose name or text contains `query` (not trashed), newest first: id, name, type, link, modified."""
    params = {
        "q": f"fullText contains '{_quote(query.strip())}' and trashed = false",
        "pageSize": str(max(1, min(limit, 25))),
        "orderBy": "modifiedTime desc",
        "fields": "files(id,name,mimeType,webViewLink,modifiedTime)",
    }
    async with httpx.AsyncClient(timeout=30, transport=transport) as http:
        res = await http.get(f"{API}/files", params=params, headers=_headers(token))
    if res.status_code != 200:
        raise DriveToolError(f"Google Drive search failed ({res.status_code}): {res.text[:200]}")
    return [
        {
            "id": f["id"],
            "name": f["name"],
            "type": f.get("mimeType", ""),
            "link": f.get("webViewLink", ""),
            "modified": f.get("modifiedTime", ""),
        }
        for f in res.json().get("files", [])
    ]


async def read_text(
    token: str | None, file_id: str, max_chars: int = MAX_READ, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, Any]:
    """A file's text: Docs, Sheets and Slides exported as plain text/CSV, text files as they are. Anything else (an
    image, a PDF, a ZIP) is refused with its type rather than returned as garbage."""
    headers = _headers(token)
    async with httpx.AsyncClient(timeout=60, transport=transport, follow_redirects=True) as http:
        meta = await http.get(f"{API}/files/{file_id}", params={"fields": "id,name,mimeType,size"}, headers=headers)
        if meta.status_code == 404:
            raise DriveToolError("No such file, or it isn't shared with the connected account.")
        if meta.status_code != 200:
            raise DriveToolError(f"Google Drive returned {meta.status_code}: {meta.text[:200]}")
        info = meta.json()
        mime = info.get("mimeType", "")
        if mime in EXPORTS:
            res = await http.get(f"{API}/files/{file_id}/export", params={"mimeType": EXPORTS[mime]}, headers=headers)
        elif mime.startswith(TEXT_TYPES):
            res = await http.get(f"{API}/files/{file_id}", params={"alt": "media"}, headers=headers)
        else:
            raise DriveToolError(f"{info.get('name')!r} is {mime or 'an unknown type'}, not a text file.")
    if res.status_code != 200:
        raise DriveToolError(f"Google Drive returned {res.status_code}: {res.text[:200]}")
    text = res.text
    return {
        "id": info["id"],
        "name": info["name"],
        "type": mime,
        "text": text[:max_chars],
        "truncated": len(text) > max_chars,
        "characters": len(text),
    }


async def write_text(
    token: str | None,
    name: str,
    text: str,
    folder_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, str]:
    """Create a plain-text file in the connected Drive (scope drive.file: only files Codewright creates)."""
    metadata: dict[str, Any] = {"name": name, "mimeType": "text/plain"}
    if folder_id:
        metadata["parents"] = [folder_id]
    files: dict[str, tuple[str, bytes | str, str]] = {
        "metadata": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
        "file": (name, text.encode("utf-8"), "text/plain"),
    }
    async with httpx.AsyncClient(timeout=60, transport=transport) as http:
        res = await http.post(
            f"{UPLOAD}?uploadType=multipart&fields=id,name,webViewLink", headers=_headers(token), files=files
        )
    if res.status_code not in (200, 201):
        raise DriveToolError(f"Google Drive upload failed ({res.status_code}): {res.text[:200]}")
    body = res.json()
    return {"id": body["id"], "name": body["name"], "link": body.get("webViewLink", "")}
