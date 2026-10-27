"""The effective LLM configuration: models.yaml + environment + changes made on the Settings page."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agent.llm.client import LLMClient, TraceSink
from agent.llm.config import ModelsConfig, ProfileName, ProfileOverride
from monoshift_api.db import AppSetting
from monoshift_api.settings import Settings

LLM_SETTINGS_KEY = "llm"


class StoredLLMSettings(BaseModel):
    active_profile: ProfileName | None = None
    overrides: dict[ProfileName, ProfileOverride] = Field(default_factory=dict)


async def load_stored(session: AsyncSession) -> StoredLLMSettings:
    row = await session.get(AppSetting, LLM_SETTINGS_KEY)
    return StoredLLMSettings.model_validate(row.value) if row else StoredLLMSettings()


async def save_stored(session: AsyncSession, stored: StoredLLMSettings) -> None:
    value: dict[str, Any] = stored.model_dump(mode="json", exclude_none=True)
    row = await session.get(AppSetting, LLM_SETTINGS_KEY)
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=LLM_SETTINGS_KEY, value=value))
    await session.commit()


class EffectiveLLM(BaseModel):
    config: ModelsConfig
    active_profile: ProfileName

    def client(self, profile: ProfileName, tracer: TraceSink | None = None) -> LLMClient:
        return LLMClient(profile, self.config.profiles[profile], tracer=tracer)


async def effective_llm(session: AsyncSession, settings: Settings) -> EffectiveLLM:
    stored = await load_stored(session)
    config = settings.load_models().with_overrides(stored.overrides)
    return EffectiveLLM(config=config, active_profile=stored.active_profile or config.default_profile)
