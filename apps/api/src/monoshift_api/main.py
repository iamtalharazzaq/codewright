"""FastAPI application entry point: `uvicorn monoshift_api.main:app`."""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI

from monoshift_api import __version__
from monoshift_api.routes import health, projects, settings
from monoshift_api.settings import get_settings


def create_app() -> FastAPI:
    logging.basicConfig(level=get_settings().log_level.upper())
    app = FastAPI(title="MonoShift API", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(settings.router)
    api.include_router(projects.router)
    app.include_router(api)
    return app


app = create_app()
