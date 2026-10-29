"""Delivering a project to Google Drive as a folder tree (the user picks folder or ZIP)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from connectors import outputs
from connectors.outputs import DeliveryError, to_drive_folder


def fake_drive(monkeypatch: pytest.MonkeyPatch) -> tuple[list[dict[str, object]], list[str]]:
    folders: list[dict[str, object]] = []
    uploaded: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/drive/v3/files":
            body = json.loads(req.content)
            folders.append(body)
            return httpx.Response(200, json={"id": f"f{len(folders)}", "webViewLink": f"https://drive/f{len(folders)}"})
        text = req.content.decode("utf-8", errors="replace")
        uploaded.append(next(line for line in text.splitlines() if line.startswith('{"name"')))
        return httpx.Response(200, json={"id": "x"})

    real = httpx.AsyncClient
    monkeypatch.setattr(outputs.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return folders, uploaded


async def test_the_folder_tree_is_recreated_and_junk_is_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src/lib").mkdir(parents=True)
    (tmp_path / "node_modules/x").mkdir(parents=True)
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    (tmp_path / "src/lib/a.ts").write_text("export {}", encoding="utf-8")
    (tmp_path / "node_modules/x/b.js").write_text("x", encoding="utf-8")
    folders, uploaded = fake_drive(monkeypatch)
    link = await to_drive_folder(tmp_path, "tok", "my-app")
    assert link == "https://drive/f1"  # the root folder
    assert [f["name"] for f in folders] == ["my-app", "src", "lib"]
    assert folders[2]["parents"] == ["f2"]  # lib sits inside src
    assert sorted(json.loads(u)["name"] for u in uploaded) == ["README.md", "a.ts"]


async def test_drive_must_be_connected(tmp_path: Path) -> None:
    with pytest.raises(DeliveryError, match="connect it in Settings"):
        await to_drive_folder(tmp_path, None, "x")
