"""Runtime settings, read from environment variables (see `.env.example`) and `config/models.yaml`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]

LLMProfileName = Literal["remote_gpu", "local_cpu"]


class LLMProfile(BaseModel):
    """One switchable LLM endpoint (README Section 8.1). Both servers expose an OpenAI-compatible API."""

    server: Literal["ollama", "llamacpp"]
    base_url: str
    model: str
    num_ctx: int = Field(gt=0)
    max_parallel_llm_jobs: int = Field(default=1, ge=1)
    # Name of the env var holding an optional API key for the model server; never the key itself.
    api_key_env: str | None = None


class EmbeddingsConfig(BaseModel):
    server: Literal["ollama", "llamacpp"]
    base_url: str
    model: str


class ModelsConfig(BaseModel):
    profiles: dict[LLMProfileName, LLMProfile]
    embeddings: EmbeddingsConfig
    default_profile: LLMProfileName

    @model_validator(mode="after")
    def _default_profile_exists(self) -> Self:
        if self.default_profile not in self.profiles:
            raise ValueError(f"default_profile {self.default_profile!r} is not defined under profiles")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> ModelsConfig:
        with path.open(encoding="utf-8") as f:
            return cls.model_validate(yaml.safe_load(f))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MONOSHIFT_", env_file=".env", extra="ignore")

    database_url: SecretStr
    models_config: Path = REPO_ROOT / "config" / "models.yaml"
    workspaces_dir: Path = REPO_ROOT / "workspaces"
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    # External (non self-hosted) LLM providers stay off unless the user opts in (README Section 8.1).
    external_llm_enabled: bool = False

    def load_models(self) -> ModelsConfig:
        return ModelsConfig.from_yaml(self.models_config)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # required fields come from the environment
