"""LLM profile configuration (README Section 8.1), loaded from `config/models.yaml`.

Both profiles talk to a llama.cpp server (or anything OpenAI-compatible) at `base_url`. Switching between the remote GPU
and the local CPU is a URL change: the rest of the config is the same.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import httpx
import yaml
from pydantic import BaseModel, Field, model_validator

ProfileName = Literal["remote_gpu", "local_cpu"]
PROFILE_NAMES: tuple[ProfileName, ...] = ("remote_gpu", "local_cpu")


class LLMProfile(BaseModel):
    server: Literal["llamacpp", "ollama", "openai_compatible"] = "llamacpp"
    # None means "not configured yet" (e.g. the remote GPU URL hasn't been provided).
    base_url: str | None = None
    model: str
    num_ctx: int = Field(gt=0)
    max_parallel_llm_jobs: int = Field(default=1, ge=1)
    request_timeout_s: float = Field(default=600, gt=0)
    # A lost server (GPU box off, tunnel down) should pause the run within seconds, not after a full request timeout.
    connect_timeout_s: float = Field(default=10, gt=0)

    def http_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.request_timeout_s, connect=self.connect_timeout_s)

    # Name of the env var holding an optional API key for the model server; never the key itself.
    api_key_env: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.base_url)


class EmbeddingsConfig(BaseModel):
    server: Literal["llamacpp", "ollama", "openai_compatible"] = "llamacpp"
    base_url: str | None = None
    model: str
    dimensions: int = Field(gt=0)


class ProfileOverride(BaseModel):
    """User changes made in Settings; they win over models.yaml."""

    base_url: str | None = None
    model: str | None = None
    num_ctx: int | None = Field(default=None, gt=0)


class ModelsConfig(BaseModel):
    profiles: dict[ProfileName, LLMProfile]
    embeddings: EmbeddingsConfig
    default_profile: ProfileName

    @model_validator(mode="after")
    def _default_profile_exists(self) -> Self:
        if self.default_profile not in self.profiles:
            raise ValueError(f"default_profile {self.default_profile!r} is not defined under profiles")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> ModelsConfig:
        with path.open(encoding="utf-8") as f:
            return cls.model_validate(yaml.safe_load(f))

    def with_overrides(self, overrides: dict[ProfileName, ProfileOverride]) -> ModelsConfig:
        profiles = dict(self.profiles)
        for name, ov in overrides.items():
            if name in profiles:
                profiles[name] = profiles[name].model_copy(update=ov.model_dump(exclude_none=True))
        return self.model_copy(update={"profiles": profiles})
