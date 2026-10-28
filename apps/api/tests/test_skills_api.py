"""Skills over the API (Phase 6 task 6) and corrections saved as facts (task 4)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from codewright_api.project_tools import save_facts
from tests.conftest import AppFactory

NOTES = """---
name: release-notes
command: /release-notes
description: Turn a list of commits into release notes with Added, Changed and Fixed sections.
---

## Instructions
1. Sort the commits into Added, Changed and Fixed.
2. One short past-tense line each.
"""


def test_create_export_import_and_enable(app_factory: AppFactory) -> None:
    with app_factory() as client:
        names = {s["name"] for s in client.get("/api/skills").json()}
        assert {"review-code", "explain", "audit", "docs"} <= names

        assert client.post("/api/skills", json={"markdown": NOTES}).status_code == 201
        bad = client.post("/api/skills", json={"markdown": NOTES.replace("release-notes", "review-code")})
        assert bad.status_code == 422 and bad.json()["detail"]["problems"]

        archive = client.get("/api/skills/release-notes/export")
        assert archive.headers["content-type"] == "application/zip"
        assert client.delete("/api/skills/release-notes").status_code == 204
        assert client.delete("/api/skills/review-code").status_code == 403  # built-ins stay

        imported = client.post("/api/skills/import", files={"file": ("notes.zip", archive.content, "application/zip")})
        assert imported.json()["imported"] == 1
        skill = client.get("/api/skills/release-notes").json()
        assert skill["enabled"] is False and skill["auto_use"] is True  # disabled until enabled; its setting kept
        assert client.patch("/api/skills/release-notes", json={"enabled": True}).json()["enabled"] is True


def _project(client: TestClient) -> str:
    return str(client.post("/api/projects", data={"kind": "empty", "name": "shop"}).json()["id"])


def test_facts_are_one_memory_item_per_pair(app_factory: AppFactory) -> None:
    with app_factory() as client:
        pid = _project(client)
        state = client.app.state  # type: ignore[attr-defined]
        sessions = state.run_manager.sessions

        def save(*facts: dict[str, str]) -> None:  # on the app's own event loop, like a request
            client.portal.call(save_facts, sessions, state.graphs, uuid.UUID(pid), list(facts))  # type: ignore[union-attr]

        save({"source": "billing", "target": "mailer", "relation": "calls"})
        save({"source": "orders", "target": "billing", "relation": "calls"})
        save({"source": "billing", "target": "mailer", "relation": "not_calls"})  # replaces the first

        memory = client.get(f"/api/projects/{pid}").json()["memory"]
        assert sorted(m["value"] for m in memory) == ["billing does not call mailer", "orders calls billing"]
        assert len(client.get(f"/api/projects/{pid}/graph/facts").json()) == 2
