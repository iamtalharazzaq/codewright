from __future__ import annotations

import asyncio
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from agent.llm.client import HealthReport
from agent.llm.config import PROFILE_NAMES, ProfileName, ProfileOverride
from codewright_api.db import SessionDep
from codewright_api.deps import ManagerDep
from codewright_api.llm_settings import EffectiveLLM, effective_llm, load_stored, save_stored
from codewright_api.settings import Settings, get_settings

router = APIRouter(tags=["settings"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


class LLMProfileView(BaseModel):
    server: str
    base_url: str | None
    model: str
    num_ctx: int
    max_parallel_llm_jobs: int
    configured: bool
    api_key_configured: bool


class SettingsView(BaseModel):
    """Secret-free view of the current settings."""

    active_llm_profile: ProfileName
    llm_profiles: dict[ProfileName, LLMProfileView]
    embeddings_model: str
    external_llm_enabled: bool


def _view(llm: EffectiveLLM, settings: Settings) -> SettingsView:
    return SettingsView(
        active_llm_profile=llm.active_profile,
        llm_profiles={
            name: LLMProfileView(
                server=p.server,
                base_url=p.base_url,
                model=p.model,
                num_ctx=p.num_ctx,
                max_parallel_llm_jobs=p.max_parallel_llm_jobs,
                configured=p.configured,
                api_key_configured=llm.client(name).api_key is not None,
            )
            for name, p in llm.config.profiles.items()
        },
        embeddings_model=llm.config.embeddings.model,
        external_llm_enabled=settings.external_llm_enabled,
    )


@router.get("/settings")
async def read_settings(session: SessionDep, settings: SettingsDep) -> SettingsView:
    return _view(await effective_llm(session, settings), settings)


class ProfileUpdate(BaseModel):
    base_url: str | None = Field(default=None, description="Empty string clears the override.")
    model: str | None = None
    num_ctx: int | None = Field(default=None, gt=0)

    @field_validator("base_url")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        if value:
            parsed = urlparse(value)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError("Use a full http(s) URL, e.g. http://100.64.0.5:8080/v1")
        return value


class LLMSettingsUpdate(BaseModel):
    active_profile: ProfileName | None = None
    profiles: dict[ProfileName, ProfileUpdate] = Field(default_factory=dict)


@router.put("/settings/llm")
async def update_llm_settings(
    body: LLMSettingsUpdate, session: SessionDep, settings: SettingsDep, manager: ManagerDep
) -> SettingsView:
    stored = await load_stored(session)
    if body.active_profile:
        stored.active_profile = body.active_profile
    for name, change in body.profiles.items():
        current = stored.overrides.get(name, ProfileOverride())
        data = current.model_dump()
        for field, value in change.model_dump(exclude_unset=True).items():
            data[field] = value or None  # "" clears an override and falls back to models.yaml / env
        stored.overrides[name] = ProfileOverride(**data)
    await save_stored(session, stored)
    llm = await manager.refresh_llm()
    return _view(llm, settings)


class HealthView(BaseModel):
    profile: ProfileName
    status: str
    base_url: str | None
    latency_ms: int | None
    server_model: str | None
    server_ctx: int | None
    server_slots: int | None
    warnings: list[str]
    detail: str | None


def _health_view(h: HealthReport) -> HealthView:
    return HealthView(
        profile=h.profile,
        status=h.status,
        base_url=h.base_url,
        latency_ms=h.latency_ms,
        server_model=h.server_model,
        server_ctx=h.server_ctx,
        server_slots=h.server_slots,
        warnings=list(h.warnings),
        detail=h.detail,
    )


@router.get("/llm/health")
async def llm_health(manager: ManagerDep, profile: ProfileName | None = None) -> list[HealthView]:
    llm = await manager.refresh_llm()
    names = [profile] if profile else list(PROFILE_NAMES)
    unknown = [n for n in names if n not in llm.config.profiles]
    if unknown:
        raise HTTPException(404, f"Unknown profile {unknown[0]}")
    reports = await asyncio.gather(*(llm.client(n).health() for n in names))
    return [_health_view(r) for r in reports]
