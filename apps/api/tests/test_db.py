"""Tests against a real PostgreSQL + pgvector (TEST_DATABASE_URL)."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from codewright_api.db import to_sqlalchemy_url

from .conftest import AppFactory


def test_migrations_create_schema_and_pgvector(migrated_db: str) -> None:
    engine = create_engine(to_sqlalchemy_url(migrated_db))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0003"
        assert conn.execute(text("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector")).scalar() == 1.0
        tables = set(conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
    engine.dispose()
    assert {"projects", "runs", "run_events", "approvals", "traces", "app_settings"} <= tables


def test_ready_when_database_is_migrated(app_factory: AppFactory) -> None:
    with app_factory() as client:
        res = client.get("/api/health/ready")
    assert res.status_code == 200
    assert res.json()["checks"] == {
        "database": "ok",
        "pgvector": "ok",
        "migrations": "0003",
        "run_manager": "ok",
    }


def test_projects_empty_then_created_by_a_run(app_factory: AppFactory) -> None:
    with app_factory() as client:
        assert client.get("/api/projects").json() == []
        run = client.post(
            "/api/runs", json={"mode": "audit", "project_name": "goshop", "options": {"stub_delay_s": 0}}
        ).json()
        projects = client.get("/api/projects").json()
    assert [p["name"] for p in projects] == ["goshop"]
    # Projects are any codebase now (migration 0003); runs record their playbook and risk tier.
    assert "mode" not in projects[0]
    assert (run["playbook"], run["tier"], run["mode"]) == ("microservices", 3, "audit")
