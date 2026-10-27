from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AppFactory

GH_TOKEN = "ghp_" + "B" * 36


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _settled(client: TestClient, project_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        project: dict[str, Any] = client.get(f"/api/projects/{project_id}").json()
        if project["status"] != "importing":
            return project
        time.sleep(0.05)
    raise AssertionError(f"still importing: {project}")


@pytest.fixture
def folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    shared, outputs = tmp_path / "local-source", tmp_path / "deliveries"
    (shared / "goshop").mkdir(parents=True)
    (shared / "goshop" / "main.go").write_text("package main\n")
    outputs.mkdir()
    monkeypatch.setenv("LOCAL_SOURCE_ROOT", str(shared))
    monkeypatch.setenv("OUTPUT_ROOT", str(outputs))
    return shared, outputs


def test_zip_import_scan_and_deliver(app_factory: AppFactory, folders: tuple[Path, Path]) -> None:
    _, outputs = folders
    archive = _zip({"goshop/main.go": "package main\n", "goshop/config.go": f'const token = "{GH_TOKEN}"\n'})
    with app_factory() as client:
        res = client.post("/api/projects", data={"kind": "zip"}, files={"file": ("goshop.zip", archive)})
        assert res.status_code == 201, res.text
        project = _settled(client, res.json()["id"])
        assert project["status"] == "ready"
        assert project["name"] == "goshop"
        assert project["summary"]["languages"] == {"Go": 2}
        assert project["secrets"] == [{"kind": "GitHub token", "path": "config.go", "line": 1}]
        assert project["branch"] == "main"

        client.patch(f"/api/projects/{project['id']}", json={"instructions": "Use testify."})
        client.post(f"/api/projects/{project['id']}/memory", json={"key": "db", "value": "postgres"})
        detail = client.get(f"/api/projects/{project['id']}").json()
        assert detail["instructions"] == "Use testify."
        assert [m["key"] for m in detail["memory"]] == ["db"]

        results = client.post("/api/deliver", json={"targets": ["zip", "local", "github"], "project_id": project["id"]})
        by_target = {r["target"]: r for r in results.json()}
        assert by_target["zip"]["ok"] and by_target["local"]["ok"]
        assert not by_target["github"]["ok"]  # no token configured: a clear error, not a crash
        download = client.get(by_target["zip"]["location"])
        assert download.status_code == 200
        assert sorted(zipfile.ZipFile(io.BytesIO(download.content)).namelist()) == ["config.go", "main.go"]
        assert len(list(outputs.iterdir())) == 1

        assert client.delete(f"/api/projects/{project['id']}").status_code == 204
        assert client.get(f"/api/projects/{project['id']}").status_code == 404


def test_malicious_zip_is_rejected(app_factory: AppFactory) -> None:
    with app_factory() as client:
        res = client.post("/api/projects", data={"kind": "zip"}, files={"file": ("evil.zip", _zip({"../x": "pwn"}))})
        project = _settled(client, res.json()["id"])
        assert project["status"] == "failed"
        assert "unsafe path" in project["error"]


def test_local_folder_import(app_factory: AppFactory, folders: tuple[Path, Path]) -> None:
    with app_factory() as client:
        assert client.get("/api/connectors").json()["local_folders"] == ["goshop"]
        ok = _settled(client, client.post("/api/projects", data={"kind": "local", "ref": "goshop"}).json()["id"])
        assert ok["status"] == "ready" and ok["summary"]["files"] == 1
        bad = _settled(client, client.post("/api/projects", data={"kind": "local", "ref": "../../etc"}).json()["id"])
        assert bad["status"] == "failed"


def test_uploads_are_scanned_and_masked(app_factory: AppFactory) -> None:
    with app_factory() as client:
        res = client.post("/api/uploads", files={"file": ("app.py", f"TOKEN = '{GH_TOKEN}'\nprint(1)\n".encode())})
        assert res.status_code == 201
        upload = res.json()
        assert upload["kind"] == "text"
        assert len(upload["secrets"]) == 1
        text = client.get(f"/api/uploads/{upload['id']}/text").json()["text"]
        assert GH_TOKEN not in text and "«secret»" in text
        assert "../" not in client.get("/api/deliveries/..%2F..%2Fetc%2Fpasswd").text
