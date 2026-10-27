from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

API_DIR = Path(__file__).resolve().parents[1]
UNREACHABLE_DB = "postgresql://unused:unused@localhost:1/unused"

# Unit tests never need a real database; DB tests read TEST_DATABASE_URL instead.
os.environ["DATABASE_URL"] = UNREACHABLE_DB

from codewright_api import db, settings  # noqa: E402
from codewright_api.main import create_app  # noqa: E402


def _clear_caches() -> None:
    settings.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.get_sessionmaker.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    _clear_caches()
    with TestClient(create_app()) as c:
        yield c
    _clear_caches()


def _test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        if os.environ.get("SKIP_DB_TESTS") == "1":
            pytest.skip("SKIP_DB_TESTS=1")
        pytest.fail(
            "DB tests need TEST_DATABASE_URL (a throwaway database; it is wiped). Set SKIP_DB_TESTS=1 to skip them."
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


AppFactory = Callable[[], TestClient]


@pytest.fixture
def app_factory(migrated_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppFactory]:
    """Builds TestClients for the real app (run manager included) on the test database.

    Each call creates a fresh app, like a restarted API process. Use it as a context manager."""
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path / "workspaces"))
    # Model servers that can't be reached: tests never depend on a real LLM.
    monkeypatch.setenv("LLM_LOCAL_CPU_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LLM_REMOTE_GPU_URL", "http://127.0.0.1:9/v1")

    def factory() -> TestClient:
        _clear_caches()
        return TestClient(create_app())

    yield factory
    _clear_caches()


def wait_for(
    client: TestClient, run_id: str, predicate: Callable[[dict[str, Any]], bool], timeout: float = 15
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run: dict[str, Any] = client.get(f"/api/runs/{run_id}").json()
        if predicate(run):
            return run
        time.sleep(0.05)
    raise AssertionError(f"timed out; last state: {run}")


def waiting(run: dict[str, Any]) -> bool:
    return run["status"] in ("waiting", "completed", "failed", "cancelled")
