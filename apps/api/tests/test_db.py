"""Tests against a real PostgreSQL + pgvector (MONOSHIFT_TEST_DATABASE_URL)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from monoshift_api.db import Project


def test_migrations_create_schema_and_pgvector(db_client: tuple[TestClient, sessionmaker[Session]]) -> None:
    _, factory = db_client
    with factory() as s:
        assert s.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0001"
        assert s.execute(text("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector")).scalar() == 1.0


def test_ready_when_database_is_migrated(db_client: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, _ = db_client
    res = client.get("/api/health/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "checks": {"database": "ok", "pgvector": "ok", "migrations": "0001"}}


def test_projects_empty_then_listed(db_client: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = db_client
    assert client.get("/api/projects").json() == []

    with factory() as s:
        s.add(Project(name="goshop", mode="audit"))
        s.commit()

    projects = client.get("/api/projects").json()
    assert len(projects) == 1
    assert projects[0]["name"] == "goshop"
    assert projects[0]["mode"] == "audit"
    assert projects[0]["status"] == "draft"
