"""Skills (CODEWRIGHT.md Section 8.6, ADR 0021): the Skills screen's API.

Built-in skills are read-only. Custom skills are created from SKILL.md text (form or Markdown editor), enabled,
disabled, deleted, exported as a ZIP and imported from a ZIP, a Git repository or a folder in the shared local
folder. Imported skills are validated, secret-scanned and stay disabled until the user enables them.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from agent.skills import TOOLS, Skill, SkillError, SkillRegistry, intent_label
from codewright_api.settings import get_settings
from connectors.inputs import clone_github, copy_local

router = APIRouter(prefix="/skills", tags=["skills"])

MAX_IMPORT_BYTES = 5 * 1024 * 1024

TEMPLATE = """---
name: my-skill
command: /my-skill
title: My skill
description: What it does and when to use it (Codewright uses this to pick the skill automatically).
languages: []
scope: global
playbook: custom
tier: 0
allowed_tools: [read_files, graph_query, code_search]
output: markdown
enabled: true
auto_use: true
---

## Instructions
1. First step.
2. Second step.

## Output format
How the result should look.
"""


def _registry(request: Request) -> SkillRegistry:
    registry: SkillRegistry | None = getattr(request.app.state, "skills", None)
    if registry is None:
        raise HTTPException(503, "Skills are unavailable.")
    return registry


def _pid(project_id: uuid.UUID | None) -> str | None:
    return str(project_id) if project_id else None


def _out(skill: Skill) -> dict[str, Any]:
    return {**skill.as_dict(), "intent_label": intent_label(skill)}


def _unprocessable(exc: SkillError) -> HTTPException:
    return HTTPException(422, {"message": str(exc), "problems": exc.problems})


class SkillIn(BaseModel):
    markdown: str = Field(min_length=10, max_length=64_000)
    project_id: uuid.UUID | None = Field(default=None, description="Save in this project's scope.")


class FlagsIn(BaseModel):
    enabled: bool | None = None
    auto_use: bool | None = None


class TryIn(BaseModel):
    input: str = Field(default="", max_length=4000)
    project_id: uuid.UUID | None = None


class ExportIn(BaseModel):
    names: list[str] = Field(min_length=1, max_length=100)
    project_id: uuid.UUID | None = None


@router.get("")
async def list_skills(request: Request, project_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    return [_out(s) for s in _registry(request).all(_pid(project_id))]


@router.get("/template")
async def template() -> dict[str, Any]:
    return {"markdown": TEMPLATE, "tools": list(TOOLS)}


@router.get("/{name}")
async def get_skill(name: str, request: Request, project_id: uuid.UUID | None = None) -> dict[str, Any]:
    try:
        return _out(_registry(request).get(name, _pid(project_id)))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


def _scoped(markdown: str, project_id: uuid.UUID | None) -> str:
    if project_id is None:
        return markdown
    return re.sub(r"(?m)^scope:.*$", f"scope: project:{project_id}", markdown, count=1)


@router.post("", status_code=201)
async def create_skill(body: SkillIn, request: Request) -> dict[str, Any]:
    try:
        return _out(_registry(request).save(_scoped(body.markdown, body.project_id)))
    except SkillError as exc:
        raise _unprocessable(exc) from exc


@router.put("/{name}")
async def replace_skill(name: str, body: SkillIn, request: Request) -> dict[str, Any]:
    registry = _registry(request)
    try:
        old = registry.get(name, _pid(body.project_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not old.editable:
        raise HTTPException(403, "Built-in skills can't be changed.")
    try:
        return _out(registry.save(_scoped(body.markdown, body.project_id), replacing=name))
    except SkillError as exc:
        raise _unprocessable(exc) from exc


@router.patch("/{name}")
async def set_flags(name: str, body: FlagsIn, request: Request, project_id: uuid.UUID | None = None) -> dict[str, Any]:
    flags = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return _out(_registry(request).set_flags(name, _pid(project_id), **flags))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except SkillError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.delete("/{name}", status_code=204)
async def delete_skill(name: str, request: Request, project_id: uuid.UUID | None = None) -> None:
    try:
        _registry(request).delete(name, _pid(project_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except SkillError as exc:
        raise HTTPException(403, str(exc)) from exc


def _zip_response(data: bytes, name: str) -> Response:
    return Response(
        data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}.zip"'}
    )


@router.post("/export")
async def export_skills(body: ExportIn, request: Request) -> Response:
    try:
        data = _registry(request).export_zip(body.names, _pid(body.project_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _zip_response(data, "skills" if len(body.names) > 1 else body.names[0])


@router.get("/{name}/export")
async def export_one(name: str, request: Request, project_id: uuid.UUID | None = None) -> Response:
    try:
        return _zip_response(_registry(request).export_zip([name], _pid(project_id)), name)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/import")
async def import_skills(
    request: Request,
    file: Annotated[UploadFile | None, File()] = None,
    git_url: Annotated[str, Form()] = "",
    folder: Annotated[str, Form()] = "",
    project_id: Annotated[uuid.UUID | None, Form()] = None,
) -> dict[str, Any]:
    """Import from a ZIP, a GitHub repository or a folder in the shared local folder. Every skill found is checked;
    good ones are saved disabled. The result lists each one with its problems or a preview."""
    registry = _registry(request)
    pid = _pid(project_id)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            if file is not None:
                archive = Path(tmp) / "skills.zip"
                data = await file.read(MAX_IMPORT_BYTES + 1)
                if len(data) > MAX_IMPORT_BYTES:
                    raise HTTPException(413, f"The ZIP is larger than {MAX_IMPORT_BYTES // 2**20} MB.")
                archive.write_bytes(data)
                results = await asyncio.to_thread(registry.import_zip, archive, project_id=pid)
            elif git_url.strip():
                token = get_settings().github_token
                dest = Path(tmp) / "repo"
                await asyncio.to_thread(
                    clone_github, git_url.strip(), dest, token.get_secret_value() if token else None
                )
                results = await asyncio.to_thread(registry.import_tree, dest, project_id=pid)
            elif folder.strip():
                dest = Path(tmp) / "folder"
                await asyncio.to_thread(copy_local, folder.strip(), get_settings().local_source_root, dest)
                results = await asyncio.to_thread(registry.import_tree, dest, project_id=pid)
            else:
                raise HTTPException(422, "Choose a ZIP file, a Git repository URL or a folder.")
        except SkillError as exc:
            raise _unprocessable(exc) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
    return {"results": results, "imported": sum(1 for r in results if r["ok"])}


@router.post("/{name}/try", status_code=201)
async def try_skill(name: str, body: TryIn, request: Request) -> dict[str, Any]:
    """Test-run: a new chat that runs this skill (even while disabled) on the sample input."""
    registry = _registry(request)
    try:
        skill = registry.get(name, _pid(body.project_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    chat = getattr(request.app.state, "chat", None)
    if chat is None:
        raise HTTPException(503, "The chat is unavailable (the run manager didn't start).")
    text = f"{skill.meta.command} {body.input}".strip()
    conv, _user, _reply = await chat.send(None, text, project_id=body.project_id, skill=skill.name)
    return {"conversation_id": str(conv.id)}
