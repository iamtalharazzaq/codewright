"""FastAPI application entry point: `uvicorn codewright_api.main:app`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from agent.llm.client import LLMClient
from agent.skills import SkillRegistry
from codewright_api import __version__
from codewright_api.chat import ChatService
from codewright_api.db import get_engine, get_sessionmaker
from codewright_api.graph import GraphService
from codewright_api.projects import ProjectService
from codewright_api.routes import (
    connectors,
    conversations,
    graph,
    health,
    playbooks,
    projects,
    runs,
    sandbox,
    settings,
    skills,
    traces,
    uploads,
    verification,
)
from codewright_api.runs import RunManager
from codewright_api.sandbox import SandboxService
from codewright_api.settings import get_settings
from codewright_api.verification import VerificationService

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg = get_settings()
    manager = RunManager(cfg, get_sessionmaker(), cfg.database_url.get_secret_value())
    app.state.graphs = GraphService(cfg, get_sessionmaker(), manager.bus)
    app.state.projects = ProjectService(cfg, get_sessionmaker(), on_ready=app.state.graphs.refresh)
    app.state.sandbox = SandboxService(cfg)
    app.state.skills = SkillRegistry(cfg.skills_dir, cfg.workspaces_dir)
    manager.graphs, manager.sandbox = app.state.graphs, app.state.sandbox
    app.state.verification = VerificationService(cfg, app.state.sandbox, llm=lambda: _llm(manager))
    manager.verification = app.state.verification
    try:
        await manager.start()  # also resumes runs interrupted by a crash or restart
        app.state.run_manager = manager
        app.state.chat = ChatService(manager, app.state.graphs, app.state.skills)
    except Exception:
        # Keep serving /api/health so the problem is visible; /api/health/ready reports it.
        log.exception("run manager failed to start")
        app.state.run_manager = None
        app.state.chat = None
    yield
    await app.state.verification.stop()
    await app.state.sandbox.stop()
    await app.state.graphs.stop()
    if app.state.chat is not None:
        await app.state.chat.stop_all()
    if app.state.run_manager is not None:
        await manager.stop()
    await get_engine().dispose()


def _llm(manager: RunManager) -> LLMClient | None:
    """The active model for work outside a run (the QA sub-agent of a verification), if the manager is up."""
    try:
        return manager.llm.client(manager.llm.active_profile)
    except RuntimeError:
        return None


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
    api.include_router(graph.router)
    api.include_router(sandbox.router)
    api.include_router(skills.router)
    api.include_router(verification.router)
    app.include_router(api)
    return app


app = create_app()
