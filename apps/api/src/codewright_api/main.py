"""FastAPI application entry point: `uvicorn codewright_api.main:app`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from codewright_api import __version__
from codewright_api.chat import ChatService
from codewright_api.db import get_engine, get_sessionmaker
from codewright_api.projects import ProjectService
from codewright_api.routes import (
    connectors,
    conversations,
    health,
    playbooks,
    projects,
    runs,
    settings,
    traces,
    uploads,
)
from codewright_api.runs import RunManager
from codewright_api.settings import get_settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg = get_settings()
    app.state.projects = ProjectService(cfg, get_sessionmaker())
    manager = RunManager(cfg, get_sessionmaker(), cfg.database_url.get_secret_value())
    try:
        await manager.start()  # also resumes runs interrupted by a crash or restart
        app.state.run_manager = manager
        app.state.chat = ChatService(manager)
    except Exception:
        # Keep serving /api/health so the problem is visible; /api/health/ready reports it.
        log.exception("run manager failed to start")
        app.state.run_manager = None
        app.state.chat = None
    yield
    if app.state.chat is not None:
        await app.state.chat.stop_all()
    if app.state.run_manager is not None:
        await manager.stop()
    await get_engine().dispose()


def create_app() -> FastAPI:
    logging.basicConfig(level=get_settings().log_level.upper())
    app = FastAPI(
        title="Codewright API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(settings.router)
    api.include_router(projects.router)
    api.include_router(playbooks.router)
    api.include_router(runs.router)
    api.include_router(traces.router)
    api.include_router(conversations.router)
    api.include_router(uploads.router)
    api.include_router(connectors.router)
    app.include_router(api)
    return app


app = create_app()
