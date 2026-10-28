"""Sandbox: build, test, lint and run a project's components; previews (CODEWRIGHT.md Phase 5, ADR 0020).

GET    /projects/{id}/sandbox                         components (with their Language Pack), runner, activities
POST   /projects/{id}/sandbox/actions                 {action, components?} → activity
GET    /projects/{id}/sandbox/actions/{aid}/events    SSE: step, output, report, result, preview, note, done
DELETE /projects/{id}/sandbox                         stop everything (previews, sidecars)
GET    /projects/{id}/sandbox/previews/{pid}/output   SSE: `output` events with base64 chunks (terminal) or text
POST   /projects/{id}/sandbox/previews/{pid}/input    {data}  (terminal previews)
POST   /projects/{id}/sandbox/previews/{pid}/resize   {rows, cols}
DELETE /projects/{id}/sandbox/previews/{pid}
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from agent.tools.sandbox import SandboxRequestError, SandboxUnavailable
from codewright_api.db import Project, SessionDep
from codewright_api.sandbox import Activity, SandboxService

router = APIRouter(prefix="/projects/{project_id}/sandbox", tags=["sandbox"])


def _service(request: Request) -> SandboxService:
    service: SandboxService | None = getattr(request.app.state, "sandbox", None)
    if service is None:
        raise HTTPException(503, "The sandbox isn't available.")
    return service


async def _project(session: SessionDep, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def _session(service: SandboxService, project_id: uuid.UUID) -> str:
    try:
        return service.session_of(project_id)
    except KeyError:
        raise HTTPException(404, "Nothing is running in the sandbox for this project.") from None


async def _forward(coro: Any) -> Any:
    try:
        return await coro
    except SandboxUnavailable as e:
        raise HTTPException(503, str(e)) from None
    except SandboxRequestError as e:
        raise HTTPException(e.status if e.status < 500 else 502, str(e)) from None


class ActionIn(BaseModel):
    action: Literal["build", "test", "lint", "audit", "run"]
    components: list[str] = Field(default=[], max_length=20, description="Component paths; empty = all.")


class InputIn(BaseModel):
    data: str = Field(max_length=65536)


class SizeIn(BaseModel):
    rows: int = Field(ge=2, le=500)
    cols: int = Field(ge=2, le=1000)


@router.get("")
async def sandbox_status(project_id: uuid.UUID, request: Request, session: SessionDep) -> dict[str, Any]:
    await _project(session, project_id)
    return await _service(request).status(project_id)


@router.post("/actions", status_code=202)
async def start_action(project_id: uuid.UUID, body: ActionIn, request: Request, session: SessionDep) -> dict[str, Any]:
    project = await _project(session, project_id)
    if project.status != "ready":
        raise HTTPException(409, "The project isn't ready yet.")
    try:
        return _service(request).start(project_id, body.action, body.components or None).summary()
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


def _activity(project_id: uuid.UUID, activity_id: str, request: Request) -> Activity:
    """As a dependency, so an unknown id is a 404 before the event stream starts."""
    activity = _service(request).activities.get(activity_id)
    if activity is None or activity.project_id != str(project_id):
        raise HTTPException(404, "No such activity")
    return activity


@router.get("/actions/{activity_id}/events", response_class=EventSourceResponse)
async def action_events(
    activity: Annotated[Activity, Depends(_activity)], request: Request, after: int = 0
) -> AsyncIterator[ServerSentEvent]:
    yield ServerSentEvent(event="ready", data=activity.summary())
    async for event in _service(request).follow(activity.id, after):
        if await request.is_disconnected():
            break
        yield ServerSentEvent(event=event["type"], data=event, id=str(event["seq"]))


@router.delete("", status_code=204)
async def stop_sandbox(project_id: uuid.UUID, request: Request) -> None:
    await _forward(_service(request).stop_session(project_id))


async def _preview(project_id: uuid.UUID, preview_id: str, request: Request) -> tuple[str, dict[str, Any]]:
    service = _service(request)
    sid = _session(service, project_id)
    return sid, await _forward(service.client.preview(sid, preview_id))


@router.get("/previews/{preview_id}/output", response_class=EventSourceResponse)
async def preview_output(
    preview: Annotated[tuple[str, dict[str, Any]], Depends(_preview)], request: Request
) -> AsyncIterator[ServerSentEvent]:
    """A preview's output from the start (scrollback), then live. Base64, so terminal control bytes survive."""
    client = _service(request).client
    sid, info = preview
    yield ServerSentEvent(event="ready", data=info)
    try:
        async for chunk in client.preview_output(sid, info["id"]):
            if await request.is_disconnected():
                break
            yield ServerSentEvent(event="output", data={"b64": base64.b64encode(chunk).decode()})
        yield ServerSentEvent(event="exit", data=await client.preview(sid, info["id"]))
    except (SandboxUnavailable, SandboxRequestError) as e:
        yield ServerSentEvent(event="error", data={"message": str(e)})


@router.post("/previews/{preview_id}/input", status_code=204)
async def preview_input(project_id: uuid.UUID, preview_id: str, body: InputIn, request: Request) -> None:
    service = _service(request)
    await _forward(service.client.send_input(_session(service, project_id), preview_id, body.data))


@router.post("/previews/{preview_id}/resize", status_code=204)
async def preview_resize(project_id: uuid.UUID, preview_id: str, body: SizeIn, request: Request) -> None:
    service = _service(request)
    await _forward(service.client.resize(_session(service, project_id), preview_id, body.rows, body.cols))


@router.delete("/previews/{preview_id}", status_code=204)
async def stop_preview(project_id: uuid.UUID, preview_id: str, request: Request) -> None:
    service = _service(request)
    await _forward(service.client.stop_preview(_session(service, project_id), preview_id))
