from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from monoshift_api import __version__
from monoshift_api.db import SessionDep

router = APIRouter(prefix="/health", tags=["health"])
log = logging.getLogger(__name__)


class Health(BaseModel):
    status: Literal["ok"]
    version: str


class Readiness(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, str]


@router.get("")
def liveness() -> Health:
    """The process is up. Does not touch dependencies."""
    return Health(status="ok", version=__version__)


@router.get("/ready", responses={503: {"model": Readiness}})
def readiness(session: SessionDep, response: Response) -> Readiness:
    """The API can serve requests: the database is reachable, pgvector is installed and migrations ran."""
    checks: dict[str, str] = {}
    try:
        session.execute(text("SELECT 1"))
        checks["database"] = "ok"
        has_vector = session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first()
        checks["pgvector"] = "ok" if has_vector else "missing"
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
        checks["migrations"] = str(revision) if revision else "missing"
    except Exception as exc:  # report, don't crash: this endpoint exists to describe failures
        log.warning("readiness check failed: %s", exc)
        checks.setdefault("database", "error")
        checks.setdefault("migrations", "unknown")

    ok = checks.get("database") == "ok" and checks.get("pgvector") == "ok" and checks.get("migrations") != "missing"
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readiness(status="ok" if ok else "unavailable", checks=checks)
