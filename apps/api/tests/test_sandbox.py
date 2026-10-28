"""Sandbox routes (Phase 5) on the real app and database, with a fake runner: components per Language Pack, live
build/test events with a parsed report, run (sidecars, migrations, previews, a frontend sharing its API's network),
the no-production guard, and the unsupported-language note on the project page."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agent.tools.sandbox import SandboxClient
from codewright_api.db import Project, get_sessionmaker
from tests.conftest import AppFactory

GO_MOD = "module example.com/shop\n\ngo 1.26\n"
MAIN_GO = 'package main\n\nimport "net/http"\n\nfunc main() { http.ListenAndServe(":8080", nil) }\n'
COMPOSE = """services:
  app:
    build: .
    ports: ["8080:8080"]
    environment:
      DATABASE_URL: postgres://postgres:pw@db:5432/postgres
    depends_on: [db]
  db:
    image: postgres:16-alpine
    environment: { POSTGRES_PASSWORD: pw }
"""
VITE = "export default { server: { proxy: { '/api': 'http://localhost:8080' } } }\n"
WEB_PACKAGE = '{"name": "web", "scripts": {"dev": "vite"}, "dependencies": {"react": "19.3.0", "vite": "8.3.4"}}'


class FakeRunner(SandboxClient):
    """Answers like the sandbox runner; `go test` prints two passing tests in `go test -json` form."""

    def __init__(self) -> None:
        super().__init__("http://fake-runner")
        self.jobs: list[dict[str, Any]] = []
        self.services: list[dict[str, Any]] = []
        self.sql: list[tuple[str, str]] = []
        self.previews: list[dict[str, Any]] = []

    async def health(self) -> dict[str, Any]:
        return {"docker": True, "gateway": True, "images": {"go": True, "node": True}}

    async def create_session(self, workspace: str, services: list[dict[str, Any]]) -> dict[str, Any]:
        return {"id": "s1", "workspace": workspace, "services": [], "previews": []}

    async def session(self, sid: str) -> dict[str, Any]:
        return {"id": sid, "services": [s["name"] for s in self.services], "previews": self.previews}

    async def add_services(self, sid: str, services: list[dict[str, Any]]) -> dict[str, Any]:
        self.services += services
        return await self.session(sid)

    async def run_sql(self, sid: str, service: str, sql: str) -> dict[str, Any]:
        self.sql.append((service, sql))
        return {"code": 0, "output": ""}

    async def job(self, sid: str, spec: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        self.jobs.append(spec)
        yield {"type": "start", "cmd": spec["cmd"]}
        if "go test" in " ".join(spec["cmd"]):
            for test in ("TestA", "TestB"):
                event = {"Action": "pass", "Package": "example.com/shop", "Test": test}
                yield {"type": "output", "stream": "stdout", "text": json.dumps(event) + "\n"}
        else:
            yield {"type": "output", "stream": "stdout", "text": "ok\n"}
        yield {"type": "exit", "code": 0, "duration_s": 0.1}

    async def start_preview(self, sid: str, spec: dict[str, Any]) -> dict[str, Any]:
        preview = {"id": f"p{len(self.previews)}", "port": spec.get("port"), "running": True, **spec}
        self.previews.append(preview)
        return preview

    async def delete_session(self, sid: str) -> None:
        self.previews.clear()


def _project(client: TestClient, tmp_path: Path, files: dict[str, str]) -> str:
    project = client.post("/api/projects", data={"kind": "empty", "name": "shop"}).json()
    work = tmp_path / "workspaces" / project["id"] / "work"
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text)
    return str(project["id"])


def _events(client: TestClient, project_id: str, activity_id: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    kind = ""
    with client.stream("GET", f"/api/projects/{project_id}/sandbox/actions/{activity_id}/events") as response:
        for line in response.iter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                events.append((kind, json.loads(line[6:])))
                if kind == "done":
                    break
    return events


def test_components_test_and_run(app_factory: AppFactory, tmp_path: Path) -> None:
    files = {
        "go.mod": GO_MOD,
        "cmd/app/main.go": MAIN_GO,
        "docker-compose.yml": COMPOSE,
        "migrations/0001_init.up.sql": "create table t (id int);",
        "config.example.yaml": "debug: true\n",
        "web/package.json": WEB_PACKAGE,
        "web/vite.config.js": VITE,
    }
    with app_factory() as client:
        fake = FakeRunner()
        client.app.state.sandbox.client = fake  # type: ignore[attr-defined]
        pid = _project(client, tmp_path, files)

        status = client.get(f"/api/projects/{pid}/sandbox").json()
        assert [(c["pack"], c["path"], c["kind"]) for c in status["components"]] == [
            ("go", ".", "api"),
            ("javascript", "web", "web"),
        ]
        assert status["components"][0]["run"] == {
            "kind": "web",
            "cmd": ["./.codewright/bin/app"],
            "port": 8080,
            "services": ["db"],
        }

        activity = client.post(f"/api/projects/{pid}/sandbox/actions", json={"action": "test", "components": ["."]})
        assert activity.status_code == 202
        events = _events(client, pid, activity.json()["id"])
        kinds = [k for k, _ in events]
        assert kinds[0] == "ready" and kinds[-1] == "done"
        assert [d["name"] for k, d in events if k == "step"] == ["install", "build", "test"]
        report = next(d["report"] for k, d in events if k == "report")
        assert (report["passed"], report["failed"], report["ok"]) == (2, 0, True)
        assert events[-1][1]["status"] == "passed"
        notes = [d["text"] for k, d in events if k == "note"]
        assert notes == ["Using the sample config: config.example.yaml → config.yaml (not committed)"]
        assert next(j for j in fake.jobs if "go test" in " ".join(j["cmd"]))["network"] == "none"

        run = client.post(f"/api/projects/{pid}/sandbox/actions", json={"action": "run"}).json()
        events = _events(client, pid, run["id"])
        assert events[-1][1]["status"] == "passed", events
        assert [s["name"] for s in fake.services] == ["db"]
        assert fake.sql == [("db", "create table t (id int);")]
        api, web = fake.previews
        assert (api["kind"], api["port"]) == ("web", 8080)
        assert api["env"]["DATABASE_URL"] == "postgres://postgres:pw@db:5432/postgres"  # from the compose file
        assert web["share_network_of"] == api["id"]  # the frontend proxies to localhost:8080
        assert client.get(f"/api/projects/{pid}/sandbox").json()["session"]["previews"] == fake.previews


def test_production_connection_strings_are_refused(app_factory: AppFactory, tmp_path: Path) -> None:
    compose = COMPOSE.replace("@db:5432", "@prod-db.example.com:5432")
    with app_factory() as client:
        fake = FakeRunner()
        client.app.state.sandbox.client = fake  # type: ignore[attr-defined]
        pid = _project(client, tmp_path, {"go.mod": GO_MOD, "main.go": MAIN_GO, "docker-compose.yml": compose})
        run = client.post(f"/api/projects/{pid}/sandbox/actions", json={"action": "run"}).json()
        events = _events(client, pid, run["id"])
        errors = [d["message"] for k, d in events if k == "error"]
        assert errors and "DATABASE_URL → prod-db.example.com" in errors[0]
        assert events[-1][1]["status"] == "failed"
        assert fake.previews == []


def test_nothing_to_run_and_unknown_activity(app_factory: AppFactory, tmp_path: Path) -> None:
    with app_factory() as client:
        client.app.state.sandbox.client = FakeRunner()  # type: ignore[attr-defined]
        pid = _project(client, tmp_path, {"README.md": "just text"})
        assert client.get(f"/api/projects/{pid}/sandbox").json()["components"] == []
        response = client.post(f"/api/projects/{pid}/sandbox/actions", json={"action": "build"})
        assert response.status_code == 422
        assert client.get(f"/api/projects/{pid}/sandbox/actions/nope/events").status_code == 404
        assert client.post(f"/api/projects/{pid}/sandbox/previews/p1/input", json={"data": "x"}).status_code == 404


def test_unsupported_language_project(app_factory: AppFactory, tmp_path: Path) -> None:
    with app_factory() as client:
        project = client.post("/api/projects", data={"kind": "empty", "name": "legacy"}).json()

        # The summary is computed at import; an empty project gets its files later, so set it as an import would.
        async def set_summary() -> None:
            async with get_sessionmaker()() as session:
                row = await session.get(Project, uuid.UUID(project["id"]))
                assert row is not None
                row.summary = {"languages": {"Java": 40, "SQL": 3}}
                await session.commit()

        client.portal.call(set_summary)  # type: ignore[union-attr]
        detail = client.get(f"/api/projects/{project['id']}").json()
        assert detail["unsupported"]["language"] == "Java"
        assert detail["unsupported"]["suggestions"] == ["Go", "TypeScript"]
        assert "translate it into Go or TypeScript" in detail["unsupported"]["message"]
