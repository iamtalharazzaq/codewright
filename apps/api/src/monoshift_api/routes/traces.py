from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from monoshift_api.db import SessionDep, Trace

router = APIRouter(prefix="/traces", tags=["traces"])


class TraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    run_id: uuid.UUID | None
    step: str | None
    role: str | None
    kind: str
    name: str
    profile: str | None
    model: str | None
    input: Any
    output: str | None
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    status: str
    error: str | None
    metadata: dict[str, Any] = Field(validation_alias="meta")
    created_at: datetime


@router.get("")
async def list_traces(session: SessionDep, run_id: uuid.UUID | None = None, limit: int = 100) -> list[TraceOut]:
    query = select(Trace).order_by(Trace.id.desc()).limit(min(limit, 500))
    if run_id:
        query = query.where(Trace.run_id == run_id)
    return [TraceOut.model_validate(t) for t in await session.scalars(query)]
