from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

API_DIR = Path(__file__).resolve().parents[1]

# Unit tests never need a real database; DB tests read MONOSHIFT_TEST_DATABASE_URL instead.
os.environ["MONOSHIFT_DATABASE_URL"] = "postgresql://unused:unused@localhost:1/unused"

from monoshift_api.db import get_session, to_sqlalchemy_url  # noqa: E402
from monoshift_api.main import create_app  # noqa: E402


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def _test_database_url() -> str:
    url = os.environ.get("MONOSHIFT_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("MONOSHIFT_SKIP_DB_TESTS") == "1":
            pytest.skip("MONOSHIFT_SKIP_DB_TESTS=1")
        pytest.fail(
            "DB tests need MONOSHIFT_TEST_DATABASE_URL (a throwaway database; it is wiped). "
            "Set MONOSHIFT_SKIP_DB_TESTS=1 to skip them."
        )
    return url


def alembic_config(url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    return cfg


@pytest.fixture
def migrated_db() -> Iterator[str]:
    """A test database migrated from scratch to head, and rolled back to empty afterwards."""
    url = _test_database_url()
    cfg = alembic_config(url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield url
    command.downgrade(cfg, "base")


@pytest.fixture
def db_client(migrated_db: str) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(to_sqlalchemy_url(migrated_db))
    factory = sessionmaker(engine, expire_on_commit=False)

    def _session() -> Iterator[Session]:
        with factory() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c, factory
    engine.dispose()
