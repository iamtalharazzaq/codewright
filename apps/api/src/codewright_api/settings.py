"""Runtime settings, read from environment variables (see `.env.example`) and `config/models.yaml`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent.llm.config import ModelsConfig, ProfileOverride

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    models_config: Path = REPO_ROOT / "config" / "models.yaml"
    workspaces_dir: Path = REPO_ROOT / "workspaces"
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    # External (non self-hosted) LLM providers stay off unless the user opts in (README Section 8.1).
    external_llm_enabled: bool = False
    # Optional URL overrides, so the model server address can change without editing models.yaml.
    llm_remote_gpu_url: str | None = None
    llm_local_cpu_url: str | None = None
    # Connectors (Phase 3). Paths are inside the container; docker-compose mounts the host folders there.
    local_source_root: Path | None = None  # "Local folder" input (LOCAL_SOURCE_DIR, read-only)
    output_root: Path | None = None  # local delivery target (ALLOWED_OUTPUT_DIRS)
    github_token: SecretStr | None = None
    secret_key: SecretStr | None = None  # encrypts stored tokens (Google Drive)
    google_oauth_client_file: Path | None = None
    public_url: str = "http://localhost:3000"  # where the browser reaches the app (OAuth redirect)
    # Sandbox runner (Phase 5, ADR 0020): the only service with Docker access.
    sandbox_url: str = "http://sandbox-runner:8200"
    # Where the API reaches a running app: the gateway forwards preview ports to the sandbox (Phase 7 replays).
    sandbox_gateway_host: str = "sandbox-gateway"
    # Global custom skills (Phase 6, ADR 0021); built-ins live in skills/builtin, project skills in the workspace.
    skills_dir: Path = REPO_ROOT / "skills" / "user"

    def load_models(self) -> ModelsConfig:
        """models.yaml with the environment's URL overrides applied (Settings-page overrides come on top)."""
        base = ModelsConfig.from_yaml(self.models_config)
        env: dict[str, ProfileOverride] = {}
        if self.llm_remote_gpu_url:
            env["remote_gpu"] = ProfileOverride(base_url=self.llm_remote_gpu_url)
        if self.llm_local_cpu_url:
            env["local_cpu"] = ProfileOverride(base_url=self.llm_local_cpu_url)
        return base.with_overrides(env)  # type: ignore[arg-type]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # required fields come from the environment
