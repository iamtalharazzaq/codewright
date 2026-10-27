"""FastAPI application entry point: `uvicorn monoshift_api.main:app`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from monoshift_api import __version__
from monoshift_api.db import get_engine, get_sessionmaker
from monoshift_api.routes import health, projects, runs, settings, traces
from monoshift_api.runs import RunManager
from monoshift_api.settings import get_settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg = get_settings()
    manager = RunManager(cfg, get_sessionmaker(), cfg.database_url.get_secret_value())
    try:
        await manager.start()  # also resumes runs interrupted by a crash or restart
        app.state.run_manager = manager
    except Exception:
        # Keep serving /api/health so the problem is visible; /api/health/ready reports it.
        log.exception("run manager failed to start")
        app.state.run_manager = None
    yield
    if app.state.run_manager is not None:
        await manager.stop()
    await get_engine().dispose()


def create_app() -> FastAPI:
    logging.basicConfig(level=get_settings().log_level.upper())
    app = FastAPI(
        title="MonoShift API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(settings.router)
    api.include_router(projects.router)
    api.include_router(runs.router)
    api.include_router(traces.router)
    app.include_router(api)
    return app


app = create_app()
