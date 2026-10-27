"""Google Drive connect/disconnect (ADR 0018)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from codewright_api import gdrive
from codewright_api.db import get_sessionmaker
from codewright_api.settings import get_settings

router = APIRouter(prefix="/connectors/gdrive", tags=["connectors"])


@router.get("/status")
async def drive_status() -> dict[str, Any]:
    return await gdrive.status(get_sessionmaker(), get_settings())


@router.get("/start")
async def drive_start() -> RedirectResponse:
    try:
        return RedirectResponse(gdrive.auth_url(get_settings()))
    except gdrive.DriveError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/callback")
async def drive_callback(code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    settings = get_settings()
    target = f"{settings.public_url.rstrip('/')}/settings"
    if error or not code:
        return RedirectResponse(f"{target}?drive=cancelled")
    try:
        await gdrive.complete(get_sessionmaker(), settings, code, state)
    except gdrive.DriveError:
        return RedirectResponse(f"{target}?drive=failed")
    return RedirectResponse(f"{target}?drive=connected")


@router.delete("", status_code=204)
async def drive_disconnect() -> None:
    await gdrive.disconnect(get_sessionmaker())
