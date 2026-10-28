"""The runner's HTTP API, reachable only on the compose network (no published port): the API is its only client.

GET    /health
POST   /sessions                          {workspace, services}        → session
GET    /sessions/{sid}                                                  → session
DELETE /sessions/{sid}
POST   /sessions/{sid}/services           [{name, image, env}]         → session
POST   /sessions/{sid}/services/{name}/sql {sql}                     → {code, output}
POST   /sessions/{sid}/jobs               {toolchain, cmd, ...}        → NDJSON events (start, output…, exit)
POST   /sessions/{sid}/previews           {kind, toolchain, cmd, ...}  → preview
GET    /sessions/{sid}/previews/{pid}/output                            → raw output (scrollback, then live)
POST   /sessions/{sid}/previews/{pid}/input   {data}
POST   /sessions/{sid}/previews/{pid}/resize  {rows, cols}
DELETE /sessions/{sid}/previews/{pid}
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from codewright_sandbox.config import Env, SandboxConfig
from codewright_sandbox.docker import Docker, DockerError
from codewright_sandbox.runner import JobSpec, PreviewSpec, Runner, SandboxError, ServiceSpec, SessionSpec, SqlSpec


class Input(BaseModel):
    data: str = Field(max_length=65536)


class Size(BaseModel):
    rows: int = Field(ge=2, le=500)
    cols: int = Field(ge=2, le=1000)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    env = Env()
    docker = Docker(env.docker_socket)
    runner = Runner(SandboxConfig.load(env.config_file), env, docker)
    await runner.start()
    app.state.runner = runner
    yield
    await runner.stop()
    await docker.close()


def create_app() -> FastAPI:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "info").upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per Docker call is noise
    app = FastAPI(title="Codewright sandbox runner", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.exception_handler(SandboxError)
    async def _sandbox_error(_: Request, exc: SandboxError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(DockerError)
    async def _docker_error(_: Request, exc: DockerError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=502)

    def runner(request: Request) -> Runner:
        r: Runner = request.app.state.runner
        return r

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        return await runner(request).health()

    @app.post("/sessions")
    async def create_session(spec: SessionSpec, request: Request) -> dict[str, Any]:
        return (await runner(request).create_session(spec)).as_dict()

    @app.get("/sessions/{sid}")
    async def get_session(sid: str, request: Request) -> dict[str, Any]:
        return runner(request).session(sid).as_dict()

    @app.post("/sessions/{sid}/services")
    async def add_services(sid: str, body: list[ServiceSpec], request: Request) -> dict[str, Any]:
        return (await runner(request).add_services(sid, body)).as_dict()

    @app.post("/sessions/{sid}/services/{name}/sql")
    async def run_sql(sid: str, name: str, body: SqlSpec, request: Request) -> dict[str, Any]:
        return await runner(request).run_sql(sid, name, body.sql)

    @app.delete("/sessions/{sid}", status_code=204)
    async def delete_session(sid: str, request: Request) -> None:
        await runner(request).delete_session(sid)

    @app.post("/sessions/{sid}/jobs")
    async def job(sid: str, spec: JobSpec, request: Request) -> StreamingResponse:
        events = runner(request).job(sid, spec)
        first = await anext(events)  # creation errors become a proper HTTP error, not a broken stream

        async def body() -> AsyncIterator[bytes]:
            yield (json.dumps(first) + "\n").encode()
            async for event in events:
                yield (json.dumps(event) + "\n").encode()

        return StreamingResponse(body(), media_type="application/x-ndjson")

    @app.post("/sessions/{sid}/previews")
    async def start_preview(sid: str, spec: PreviewSpec, request: Request) -> dict[str, Any]:
        return (await runner(request).start_preview(sid, spec)).as_dict()

    @app.get("/sessions/{sid}/previews/{pid}")
    async def get_preview(sid: str, pid: str, request: Request) -> dict[str, Any]:
        return runner(request).preview(sid, pid).as_dict()

    @app.get("/sessions/{sid}/previews/{pid}/output")
    async def preview_output(sid: str, pid: str, request: Request) -> StreamingResponse:
        output = runner(request).preview(sid, pid).output
        return StreamingResponse(output.follow(), media_type="application/octet-stream")

    @app.post("/sessions/{sid}/previews/{pid}/input", status_code=204)
    async def preview_input(sid: str, pid: str, body: Input, request: Request) -> None:
        await runner(request).send_input(sid, pid, body.data)

    @app.post("/sessions/{sid}/previews/{pid}/resize", status_code=204)
    async def preview_resize(sid: str, pid: str, body: Size, request: Request) -> None:
        await runner(request).resize(sid, pid, body.rows, body.cols)

    @app.delete("/sessions/{sid}/previews/{pid}", status_code=204)
    async def stop_preview(sid: str, pid: str, request: Request) -> None:
        await runner(request).stop_preview(sid, pid)

    return app


app = create_app()
