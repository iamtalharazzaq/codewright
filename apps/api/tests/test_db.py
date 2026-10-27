"""Tests against a real PostgreSQL + pgvector (TEST_DATABASE_URL)."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from codewright_api.db import to_sqlalchemy_url

from .conftest import AppFactory


def test_migrations_create_schema_and_pgvector(migrated_db: str) -> None:
    engine = create_engine(to_sqlalchemy_url(migrated_db))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0008"
        assert conn.execute(text("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector")).scalar() == 1.0
        tables = set(conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
    engine.dispose()
    assert {"projects", "runs", "run_events", "approvals", "traces", "app_settings", "uploads", "code_chunks"} <= tables


def test_ready_when_database_is_migrated(app_factory: AppFactory) -> None:
    with app_factory() as client:
        res = client.get("/api/health/ready")
    assert res.status_code == 200
    assert res.json()["checks"] == {
        "database": "ok",
        "pgvector": "ok",
        "migrations": "0008",
        "run_manager": "ok",
    }


def test_projects_empty_then_created_by_a_run(app_factory: AppFactory) -> None:
    with app_factory() as client:
        assert client.get("/api/projects").json() == []
        body = {"playbook": "architecture_change", "project_name": "goshop", "inputs": {"stub_delay_s": 0}}
        run = client.post("/api/runs", json=body).json()
        projects = client.get("/api/projects").json()
        client.post(f"/api/runs/{run['id']}/cancel")
        # A general request has no project (migration 0004).
        sample = client.post("/api/runs", json={"playbook": "sample", "inputs": {"use_llm": False}}).json()
        client.post(f"/api/runs/{sample['id']}/cancel")
    assert [p["name"] for p in projects] == ["goshop"]
    assert "mode" not in projects[0]
    # Runs record their playbook, tier and validated inputs (defaults filled in).
    assert (run["playbook"], run["tier"], run["inputs"]["mode"]) == ("architecture_change", 3, "audit")
    assert run["inputs"]["services"] == ["notification", "payment"]
    assert sample["project_id"] is None and sample["tier"] == 2
