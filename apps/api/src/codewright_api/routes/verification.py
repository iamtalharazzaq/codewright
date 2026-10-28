"""Verification: characterization journeys, recordings, replays and their reports (CODEWRIGHT.md Phase 7).

GET  /projects/{id}/verification                        recordings, reports, journeys, noise rules, activities
POST /projects/{id}/verification/actions                {action: test|characterize|record|record-live|replay|bench|
                                                         screens, component?, recording?, intents?, self_check?,
                                                         accept?} → activity
GET  /projects/{id}/verification/actions/{aid}/events   SSE: note, app, exchange, replayed, recorder, recording, report,
                                                         done
POST /projects/{id}/verification/recorder/stop          stop the live recorder (the recording is then saved)
POST /projects/{id}/verification/recordings/har         a HAR file (from a browser's developer tools) → a recording
GET  /projects/{id}/verification/reports/{rid}          one report (replay: every request and difference)
GET  /projects/{id}/verification/recordings/{rid}       one recording (every request and answer)
GET  /projects/{id}/verification/screens/{run}/{file}   a screenshot (or its diff image)
GET  /projects/{id}/verification/journeys               the journeys, in full
PUT  /projects/{id}/verification/journeys               the user's edits
GET  /projects/{id}/verification/noise                  noise rules (built-in and the project's)
PUT  /projects/{id}/verification/noise                  {enabled: {rule: bool}, rules: [own rules]}
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from agent.verification import journeys
from agent.verification.noise import NoiseRules, Rule
from codewright_api.db import Project, SessionDep
from codewright_api.sandbox import Activity
from codewright_api.verification import VerificationService

router = APIRouter(prefix="/projects/{project_id}/verification", tags=["verification"])


def _service(request: Request) -> VerificationService:
    service: VerificationService | None = getattr(request.app.state, "verification", None)
    if service is None:
        raise HTTPException(503, "Verification isn't available.")
    return service


async def _project(session: SessionDep, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


class IntentIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=300)
    path: str = Field(default="**", max_length=300)
    reason: str = Field(default="", max_length=500)


class ActionIn(BaseModel):
    action: Literal["characterize", "record", "record-live", "replay", "test", "bench", "screens"]
    component: str | None = None
    recording: str | None = None
    intents: list[IntentIn] = Field(default_factory=list, max_length=50)
    self_check: bool = True
    accept: bool = False  # screens: these screenshots become the ones later runs are compared with


class RuleIn(BaseModel):
    id: str = Field(min_length=1, max_length=60, pattern=r"^[\w.-]+$")
    kind: Literal["ignore", "id", "timestamp", "token", "tolerance", "unordered"]
    description: str = Field(default="", max_length=300)
    where: str = Field(min_length=1, max_length=300)
    tolerance: float = Field(default=0.0, ge=0, le=1)
    enabled: bool = True


class NoiseIn(BaseModel):
    enabled: dict[str, bool] = Field(default_factory=dict)  # built-in rule → on/off
    rules: list[RuleIn] = Field(default_factory=list, max_length=100)


@router.get("")
async def verification_status(project_id: uuid.UUID, request: Request, session: SessionDep) -> dict[str, Any]:
    await _project(session, project_id)
    return _service(request).summary(project_id)


@router.post("/actions", status_code=202)
async def start_action(project_id: uuid.UUID, body: ActionIn, request: Request, session: SessionDep) -> dict[str, Any]:
    await _project(session, project_id)
    options = body.model_dump()
    options["intents"] = [i.model_dump() for i in body.intents]
    try:
        activity = _service(request).start(project_id, body.action, options)
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    return activity.summary()


@router.post("/recorder/stop", status_code=202)
async def stop_recorder(project_id: uuid.UUID, request: Request) -> dict[str, bool]:
    if not _service(request).stop_recorder(project_id):
        raise HTTPException(409, "The recorder isn't running.")
    return {"stopping": True}


@router.post("/recordings/har", status_code=201)
async def import_har(
    project_id: uuid.UUID, body: dict[str, Any], request: Request, session: SessionDep, component: str | None = None
) -> dict[str, Any]:
    await _project(session, project_id)
    try:
        return _service(request).import_har(project_id, body, component)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(422, f"Not a usable HAR file: {e}") from None


@router.get("/screens/{run_id}/{name}")
async def get_screenshot(project_id: uuid.UUID, run_id: str, name: str, request: Request) -> FileResponse:
    try:
        return FileResponse(_service(request).screenshot(project_id, run_id, name), media_type="image/png")
    except KeyError:
        raise HTTPException(404, "No such screenshot") from None


def _activity(project_id: uuid.UUID, activity_id: str, request: Request) -> Activity:
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


@router.get("/reports/{report_id}")
async def get_report(project_id: uuid.UUID, report_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).report(project_id, report_id)
    except KeyError:
        raise HTTPException(404, "No such report") from None


@router.get("/recordings/{recording_id}")
async def get_recording(project_id: uuid.UUID, recording_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).recording(project_id, recording_id).as_dict()
    except KeyError:
        raise HTTPException(404, "No such recording") from None


@router.get("/journeys")
async def get_journeys(project_id: uuid.UUID, request: Request) -> list[dict[str, Any]]:
    return [asdict(j) for j in _service(request).saved_journeys(project_id)]


@router.put("/journeys")
async def put_journeys(project_id: uuid.UUID, body: list[dict[str, Any]], request: Request) -> list[dict[str, Any]]:
    try:
        parsed = journeys.journeys_from_json(body)
    except (KeyError, TypeError) as e:
        raise HTTPException(422, f"Not a journey list: {e}") from None
    service = _service(request)
    journeys.save_journeys(parsed, service.folder(project_id) / "journeys.json")
    return [asdict(j) for j in parsed]


@router.get("/noise")
async def get_noise(project_id: uuid.UUID, request: Request) -> list[dict[str, Any]]:
    return _service(request).rules(project_id).as_list()


@router.put("/noise")
async def put_noise(project_id: uuid.UUID, body: NoiseIn, request: Request) -> list[dict[str, Any]]:
    service = _service(request)
    rules = NoiseRules()
    for r in rules.rules:
        r.enabled = body.enabled.get(r.id, r.enabled)
    builtin = {r.id for r in rules.rules}
    rules.rules += [Rule(**r.model_dump()) for r in body.rules if r.id not in builtin]
    rules.save(service.folder(project_id) / "noise.json")
    return rules.as_list()
