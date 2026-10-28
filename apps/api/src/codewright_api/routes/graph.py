"""Project graph, code search and live graph events (CODEWRIGHT.md Section 8.2, Phase 4)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from agent.graphify import GraphifyError
from codewright_api.db import Project, SessionDep
from codewright_api.graph import GraphService, bus_key

router = APIRouter(prefix="/projects/{project_id}", tags=["graph"])


def _graphs(request: Request) -> GraphService:
    service: GraphService | None = getattr(request.app.state, "graphs", None)
    if service is None:
        raise HTTPException(503, "Graphs are not available (is the database reachable?).")
    return service


async def _project(session: SessionDep, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


class RefreshIn(BaseModel):
    paths: list[str] = Field(default=[], max_length=1000, description="Files just written; empty = everything.")
    reason: str = Field(default="update", max_length=100)


@router.get("/graph")
async def get_graph(
    project_id: uuid.UUID, request: Request, session: SessionDep, version: int | None = None
) -> dict[str, Any]:
    """The module graph of a version (latest by default), the version list for the timeline, and whether an update
    is running."""
    await _project(session, project_id)
    graphs = _graphs(request)
    store = graphs.store(project_id)
    versions = store.versions()
    return {
        "versions": versions,
        "version": version or (versions[-1]["number"] if versions else None),
        "graph": store.modules(version),
        "building": graphs.building(project_id),
    }


@router.get("/graph/facts")
async def list_facts(project_id: uuid.UUID, request: Request, session: SessionDep) -> list[dict[str, Any]]:
    """Corrections the user confirmed (USER_FACT): the strongest evidence on the graph."""
    await _project(session, project_id)
    return _graphs(request).store(project_id).facts()


@router.delete("/graph/facts", status_code=204)
async def remove_fact(project_id: uuid.UUID, source: str, target: str, request: Request, session: SessionDep) -> None:
    await _project(session, project_id)
    graphs = _graphs(request)
    graphs.store(project_id).remove_fact(source, target)
    graphs.facts_changed(project_id)


@router.post("/graph", status_code=202)
async def refresh_graph(
    project_id: uuid.UUID, body: RefreshIn, request: Request, session: SessionDep
) -> dict[str, bool]:
    """Ask for an update (throttled). Builders call this after writing files so the Graph tab follows live."""
    await _project(session, project_id)
    _graphs(request).refresh(project_id, body.paths, body.reason)
    return {"queued": True}


@router.get("/graph/ask")
async def ask_graph(
    project_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    explain: str | None = None,
    query: str | None = None,
    a: str | None = None,
    b: str | None = None,
) -> dict[str, str]:
    """Graphify's own answers: `explain` a node, `query` (a question), or the path from `a` to `b`."""
    await _project(session, project_id)
    store = _graphs(request).store(project_id)
    try:
        if explain:
            answer = await asyncio.to_thread(store.explain, explain)
        elif query:
            answer = await asyncio.to_thread(store.query, query)
        elif a and b:
            answer = await asyncio.to_thread(store.path, a, b)
        else:
            raise HTTPException(422, "Give explain, query, or a and b.")
    except GraphifyError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"answer": answer}


@router.get("/search")
async def search_code(project_id: uuid.UUID, q: str, request: Request, session: SessionDep) -> list[dict[str, Any]]:
    await _project(session, project_id)
    return await _graphs(request).search(project_id, q)


@router.get("/events", response_class=EventSourceResponse)
async def project_events(project_id: uuid.UUID, request: Request) -> AsyncIterator[ServerSentEvent]:
    """Live graph updates: `working` (modules being changed), `graph_building`, `graph` (a new version and its diff),
    `graph_error`."""
    bus = _graphs(request).bus
    key = bus_key(project_id)
    queue = bus.subscribe(key)
    try:
        yield ServerSentEvent(event="ready", data={})
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5)
            except TimeoutError:
                continue
            yield ServerSentEvent(event=event["type"], data=event)
    finally:
        bus.unsubscribe(key, queue)
