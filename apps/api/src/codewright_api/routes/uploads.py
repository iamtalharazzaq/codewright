"""Chat uploads (CODEWRIGHT.md Section 2.2): stored on disk, scanned for secrets. Text is read as data only, with
secrets masked, never as instructions."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict

from agent.tools.secrets import TEXT_SUFFIX_DENY, mask, scan_text
from codewright_api.db import SessionDep, Upload
from codewright_api.settings import get_settings

router = APIRouter(tags=["uploads"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_TEXT_CHARS = 12_000  # read limit; the chat prompt takes less (chat.ATTACHMENT_CHARS)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ARCHIVE_SUFFIXES = {".zip", ".gz", ".tar", ".tgz"}


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    size: int
    kind: str
    secrets: list[dict[str, Any]]
    created_at: datetime


def _kind(name: str, data: bytes) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in ARCHIVE_SUFFIXES:
        return "archive"
    if suffix in TEXT_SUFFIX_DENY or b"\0" in data[:8192]:
        return "other"
    return "text"


def read_masked(upload: Upload) -> str:
    """The upload's text with secrets masked, cut to what fits in a prompt. Empty for non-text files."""
    if upload.kind != "text":
        return ""
    try:
        text = Path(upload.path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return mask(text[:MAX_TEXT_CHARS])


@router.post("/uploads", response_model=UploadOut, status_code=201)
async def create_upload(
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    conversation_id: Annotated[uuid.UUID | None, Form()] = None,
    project_id: Annotated[uuid.UUID | None, Form()] = None,
) -> Upload:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Files up to {MAX_UPLOAD_BYTES // 2**20} MB.")
    name = Path(file.filename or "file").name[:200] or "file"
    upload_id = uuid.uuid4()
    folder = get_settings().workspaces_dir / "_uploads" / str(upload_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    kind = _kind(name, data)
    findings = []
    if kind == "text":
        findings = [f.as_dict() for f in scan_text(data.decode("utf-8", errors="replace"), name)]
    row = Upload(
        id=upload_id,
        conversation_id=conversation_id,
        project_id=project_id,
        filename=name,
        content_type=(file.content_type or "application/octet-stream")[:100],
        size=len(data),
        kind=kind,
        path=str(path),
        secrets=findings,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.get("/uploads/{upload_id}/text")
async def upload_text(upload_id: uuid.UUID, session: SessionDep) -> dict[str, str]:
    row = await session.get(Upload, upload_id)
    if row is None:
        raise HTTPException(404, "Upload not found")
    return {"filename": row.filename, "text": read_masked(row)}
