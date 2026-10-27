from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from agent.graph.gates import GATES
from agent.graph.steps import STEPS
from agent.llm.config import ProfileName
from codewright_api.db import Approval, Run, RunEvent, SessionDep, Trace, get_sessionmaker
from codewright_api.deps import ManagerDep
from codewright_api.runs import TERMINAL_STATUSES, RunConflict, event_dict

router = APIRouter(prefix="/runs", tags=["runs"])


class RunOptions(BaseModel):
    stub_delay_s: float = Field(default=2.0, ge=0, le=60, description="How long each stub step takes.")
    use_llm: bool = Field(default=False, description="Make one real LLM call at intake.")
    services: list[str] = Field(default_factory=lambda: ["notification", "payment"], max_length=10)


class RunCreate(BaseModel):
    project_name: str = Field(default="Demo project", min_length=1, max_length=200)
    mode: Literal["conversion", "audit"]
    llm_profile: ProfileName | None = None
    options: RunOptions = Field(default_factory=RunOptions)


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    llm_calls: int
    llm_time_ms: int


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    playbook: str
    tier: int
    mode: str
    status: str
    llm_profile: str
    options: dict[str, Any]
    current_step: str | None
    pending: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class RunDetail(RunOut):
    usage: Usage
    approvals: list[dict[str, Any]]


class WorkflowView(BaseModel):
    steps: list[dict[str, Any]]
    gates: list[dict[str, Any]]


@router.get("/workflow")
async def workflow() -> WorkflowView:
    """Static description of steps and gates, for the run timeline."""
    return WorkflowView(
        steps=[{"id": s.id, "title": s.title, "role": s.role, "number": s.number} for s in STEPS.values()],
        gates=[{"id": g.id, "number": g.number, "title": g.title, "reworks": g.reworks} for g in GATES.values()],
    )


@router.post("", status_code=201)
async def create_run(body: RunCreate, manager: ManagerDep) -> RunOut:
    try:
        run = await manager.create_run(
            project_name=body.project_name,
            mode=body.mode,
            llm_profile=body.llm_profile,
            options=body.options.model_dump(),
        )
    except RunConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return RunOut.model_validate(run)


@router.get("")
async def list_runs(session: SessionDep, limit: int = 20) -> list[RunOut]:
    rows = await session.scalars(select(Run).order_by(Run.created_at.desc()).limit(min(limit, 100)))
    return [RunOut.model_validate(r) for r in rows]


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, session: SessionDep) -> RunDetail:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(Trace.prompt_tokens), 0),
                func.coalesce(func.sum(Trace.completion_tokens), 0),
                func.count(Trace.id),
                func.coalesce(func.sum(Trace.latency_ms), 0),
            ).where(Trace.run_id == run_id, Trace.kind == "llm")
        )
    ).one()
    approvals = await session.scalars(select(Approval).where(Approval.run_id == run_id).order_by(Approval.id))
    return RunDetail(
        **RunOut.model_validate(run).model_dump(),
        usage=Usage(prompt_tokens=totals[0], completion_tokens=totals[1], llm_calls=totals[2], llm_time_ms=totals[3]),
        approvals=[
            {"gate": a.gate, "subject": a.subject, "decision": a.decision, "comment": a.comment, "at": a.created_at}
            for a in approvals
        ],
    )


class Answer(BaseModel):
    """The user's answer to the run's open prompt."""

    decision: Literal["approve", "edit", "reject"] | None = None
    comment: str = Field(default="", max_length=4000)
    edits: dict[str, Any] = Field(default_factory=dict)
    choice: Literal["retry", "switch_to_cpu"] | None = Field(
        default=None, description="For a 'model server unavailable' prompt."
    )


@router.post("/{run_id}/answer", status_code=202)
async def answer(run_id: uuid.UUID, body: Answer, manager: ManagerDep) -> dict[str, str]:
    value: Any
    if body.choice:
        value = body.choice
    elif body.decision:
        if body.decision != "approve" and not body.comment.strip():
            raise HTTPException(422, "Edit and Reject need a comment explaining what to change.")
        value = {"decision": body.decision, "comment": body.comment, "edits": body.edits}
    else:
        raise HTTPException(422, "Send a decision (gate) or a choice (model server prompt).")
    try:
        await manager.answer(run_id, value)
    except LookupError as exc:
        raise HTTPException(404, "Run not found") from exc
    except RunConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "resumed"}


@router.post("/{run_id}/cancel", status_code=202)
async def cancel(run_id: uuid.UUID, session: SessionDep, manager: ManagerDep) -> dict[str, str]:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    if run.status in ("completed", "failed", "cancelled"):
        raise HTTPException(409, f"Run is already {run.status}")
    await manager.cancel(run_id)
    return {"status": "cancelled"}


@router.get("/{run_id}/events", response_class=EventSourceResponse)
async def events(
    run_id: uuid.UUID,
    request: Request,
    manager: ManagerDep,
    after: int = 0,
    follow: bool = True,
    last_event_id: str | None = Header(default=None),
) -> AsyncIterator[ServerSentEvent]:
    """Run timeline as Server-Sent Events: past events first, then live ones until the run ends.

    Reconnecting clients resume after `Last-Event-ID`. `follow=false` returns only the past events."""
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
    queue = manager.bus.subscribe(str(run_id))  # subscribe before reading the backlog so nothing is missed
    try:
        async with get_sessionmaker()() as session:
            backlog = await session.scalars(
                select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.id > cursor).order_by(RunEvent.id)
            )
            for row in backlog:
                cursor = row.id
                yield ServerSentEvent(id=str(row.id), event="run_event", data=event_dict(row))
            run = await session.get(Run, run_id)
        if not follow or run is None or run.status in TERMINAL_STATUSES:
            return
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5)
            except TimeoutError:
                continue  # FastAPI also sends keep-alive pings on its own
            if event["id"] <= cursor:
                continue
            cursor = event["id"]
            yield ServerSentEvent(id=str(event["id"]), event="run_event", data=event)
            if event["type"] == "run_status" and event["data"].get("status") in TERMINAL_STATUSES:
                return
    finally:
        manager.bus.unsubscribe(str(run_id), queue)
