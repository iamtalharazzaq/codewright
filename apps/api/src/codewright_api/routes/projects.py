"""Projects (CODEWRIGHT.md Section 2.3 "Project home" / "New project"): connect from ZIP, GitHub, local folder or
Google Drive, or start empty; instructions, memory, chats, runs; delivery."""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from codewright_api.db import Conversation, MemoryItem, Project, Run, SessionDep
from codewright_api.gdrive import status as drive_status
from codewright_api.projects import TARGETS, ProjectService, workspace
from codewright_api.settings import get_settings
from connectors.outputs import DeliveryError

router = APIRouter(tags=["projects"])

MAX_ZIP_BYTES = 300 * 1024 * 1024


def _service(request: Request) -> ProjectService:
    service: ProjectService | None = getattr(request.app.state, "projects", None)
    if service is None:
        raise HTTPException(503, "Projects are not available (is the database reachable?).")
    return service


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    source: dict[str, Any]
    summary: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectOut):
    instructions: str
    secrets: list[dict[str, Any]]
    branch: str | None = None
    chats: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    memory: list[dict[str, Any]] = []


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    instructions: str | None = Field(default=None, max_length=20000)


class MemoryIn(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=5000)


class DeliverIn(BaseModel):
    targets: list[Literal["local", "zip", "github", "drive"]] = Field(min_length=1)
    project_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    github_repo: str | None = None


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(session: SessionDep) -> list[Project]:
    return list(await session.scalars(select(Project).order_by(Project.updated_at.desc())))


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    request: Request,
    kind: Annotated[Literal["zip", "github", "local", "drive", "empty"], Form()],
    name: Annotated[str, Form()] = "",
    ref: Annotated[str, Form()] = "",
    file: Annotated[UploadFile | None, File()] = None,
) -> Project:
    """Start an import. The project is `importing` until its files are in place, then `ready` or `failed`."""
    upload: Path | None = None
    if kind == "zip":
        if file is None:
            raise HTTPException(422, "Choose a ZIP file.")
        settings = get_settings()
        settings.workspaces_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.workspaces_dir, suffix=".zip", delete=False) as tmp:
            written = 0
            while chunk := await file.read(1 << 20):
                written += len(chunk)
                if written > MAX_ZIP_BYTES:
                    Path(tmp.name).unlink(missing_ok=True)
                    raise HTTPException(413, f"The ZIP is larger than {MAX_ZIP_BYTES // 2**20} MB.")
                tmp.write(chunk)
            upload = Path(tmp.name)
        ref = file.filename or "upload.zip"
    elif kind in ("github", "local", "drive") and not ref.strip():
        raise HTTPException(422, "Enter the repository URL, folder or Drive link.")
    default_name = Path(ref.rstrip("/")).stem.removesuffix(".git") if ref else "New project"
    return await _service(request).create(name or default_name, kind, ref.strip(), upload)


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: uuid.UUID, request: Request, session: SessionDep) -> ProjectDetail:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    chats = await session.scalars(
        select(Conversation).where(Conversation.project_id == project_id).order_by(Conversation.updated_at.desc())
    )
    runs = await session.scalars(select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc()))
    memory = await session.scalars(select(MemoryItem).where(MemoryItem.project_id == project_id))
    detail = ProjectDetail.model_validate(project)
    detail.chats = [{"id": str(c.id), "title": c.title, "updated_at": c.updated_at.isoformat()} for c in chats]
    detail.runs = [{"id": str(r.id), "playbook": r.playbook, "status": r.status} for r in runs]
    detail.memory = [{"id": m.id, "key": m.key, "value": m.value} for m in memory]
    if project.status == "ready":
        ws = workspace(_service(request).settings, project_id)
        if (ws.work / ".git").exists():
            detail.branch = ws.current_branch()
    return detail


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def patch_project(project_id: uuid.UUID, body: ProjectPatch, session: SessionDep) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    if body.name is not None:
        project.name = body.name.strip()
    if body.instructions is not None:
        project.instructions = body.instructions
    await session.commit()
    await session.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: uuid.UUID, request: Request, session: SessionDep) -> None:
    """Deletes the project and its workspace copy. The original source (repo, ZIP, folder) is never touched."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    await session.delete(project)
    await session.commit()
    await _service(request).delete(project_id)


@router.post("/projects/{project_id}/memory", status_code=201)
async def add_memory(project_id: uuid.UUID, body: MemoryIn, session: SessionDep) -> dict[str, Any]:
    row = await session.scalar(
        select(MemoryItem).where(MemoryItem.project_id == project_id, MemoryItem.key == body.key)
    )
    if row is None:
        row = MemoryItem(project_id=project_id, key=body.key, value=body.value, source="user")
        session.add(row)
    else:
        row.value = body.value
    await session.commit()
    return {"id": row.id, "key": row.key, "value": row.value}


@router.delete("/projects/{project_id}/memory/{item_id}", status_code=204)
async def delete_memory(project_id: uuid.UUID, item_id: int, session: SessionDep) -> None:
    await session.execute(delete(MemoryItem).where(MemoryItem.id == item_id, MemoryItem.project_id == project_id))
    await session.commit()


@router.post("/deliver")
async def deliver(body: DeliverIn, request: Request, session: SessionDep) -> list[dict[str, Any]]:
    """Deliver a project (its work/ branch) or a run's output to one or more targets (C7: the user chooses)."""
    project = await session.get(Project, body.project_id) if body.project_id else None
    run = await session.get(Run, body.run_id) if body.run_id else None
    if project is None and run is not None and run.project_id is not None:
        project = await session.get(Project, run.project_id)
    if project is None and run is None:
        raise HTTPException(404, "Nothing to deliver: no such project or run.")
    try:
        return await _service(request).deliver(
            [t for t in body.targets if t in TARGETS], project=project, run=run, github_repo=body.github_repo
        )
    except DeliveryError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/deliveries/{name}")
async def download_delivery(name: str) -> FileResponse:
    folder = (get_settings().workspaces_dir / "_deliveries").resolve()
    path = (folder / name).resolve()
    if not path.is_relative_to(folder) or not path.is_file() or path.suffix != ".zip":
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="application/zip", filename=name)


@router.get("/connectors")
async def connectors(request: Request) -> dict[str, Any]:
    """What each connector needs, for the New project form and the Deliver card."""
    settings = _service(request).settings

    local_root = settings.local_source_root
    folders = sorted(p.name for p in local_root.iterdir() if p.is_dir()) if local_root and local_root.is_dir() else []
    return {
        "github_token": settings.github_token is not None and bool(settings.github_token.get_secret_value()),
        "local_folders": folders[:200],
        "output_folder": bool(settings.output_root and settings.output_root.is_dir()),
        "drive": await drive_status(_service(request).sessions, settings),
    }
