from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from monoshift_api.settings import LLMProfileName, Settings, get_settings

router = APIRouter(prefix="/settings", tags=["settings"])


class LLMProfileView(BaseModel):
    server: str
    base_url: str
    model: str
    num_ctx: int
    max_parallel_llm_jobs: int
    api_key_configured: bool


class SettingsView(BaseModel):
    """Read-only, secret-free view of the current settings. Editing arrives with Settings in Phase 1."""

    default_llm_profile: LLMProfileName
    llm_profiles: dict[LLMProfileName, LLMProfileView]
    embeddings_model: str
    external_llm_enabled: bool


@router.get("")
def read_settings(settings: Annotated[Settings, Depends(get_settings)]) -> SettingsView:
    models = settings.load_models()
    return SettingsView(
        default_llm_profile=models.default_profile,
        llm_profiles={
            name: LLMProfileView(
                server=p.server,
                base_url=p.base_url,
                model=p.model,
                num_ctx=p.num_ctx,
                max_parallel_llm_jobs=p.max_parallel_llm_jobs,
                api_key_configured=bool(p.api_key_env and os.environ.get(p.api_key_env)),
            )
            for name, p in models.profiles.items()
        },
        embeddings_model=models.embeddings.model,
        external_llm_enabled=settings.external_llm_enabled,
    )
