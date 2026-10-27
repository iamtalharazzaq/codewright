from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from monoshift_api.db import Project, SessionDep

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    mode: Literal["conversion", "audit"]
    status: str
    created_at: datetime
    updated_at: datetime


@router.get("")
async def list_projects(session: SessionDep) -> list[ProjectOut]:
    rows = await session.scalars(select(Project).order_by(Project.updated_at.desc()))
    return [ProjectOut.model_validate(p) for p in rows]
