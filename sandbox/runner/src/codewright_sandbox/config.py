"""`config/sandbox.yaml`, validated, plus the runner's environment."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

UID = 10001  # the sandbox user in every toolchain image; also the API's user, so both can write workspaces


class Limits(BaseModel):
    cpus: float = 2
    memory_mb: int = 2048
    pids: int = 512
    timeout_s: int = 900


class LimitsConfig(BaseModel):
    default: Limits = Limits()
    max: Limits = Limits(cpus=4, memory_mb=4096, pids=1024, timeout_s=1800)
    output_bytes: int = 2_000_000
    home_mb: int = 1024
    tmp_mb: int = 1024


class ServiceKind(BaseModel):
    images: list[str]
    ready: list[str] = []
    memory_mb: int = 512
    # How to run SQL in it (migrations): {sql} and {VAR:default} (the service's environment) are filled in.
    sql: list[str] = []


class Previews(BaseModel):
    first_port: int = 41000
    count: int = 10


class Egress(BaseModel):
    allow: list[str] = []


class SandboxConfig(BaseModel):
    images: dict[str, str]
    limits: LimitsConfig = LimitsConfig()
    session_ttl_s: int = 7200
    no_new_privileges: bool = False
    max_sessions: int = 4
    caches: dict[str, dict[str, str]] = {}
    services: dict[str, ServiceKind] = {}
    egress: Egress = Egress()
    previews: Previews = Previews()

    @classmethod
    def load(cls, path: Path) -> SandboxConfig:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def service_kind(self, image: str) -> str | None:
        """Which allowed service an image reference is (`postgres:16-alpine` → postgres), or None."""
        repo = image.split("@", 1)[0]
        last = repo.rsplit("/", 1)[-1]
        if ":" in last:
            repo = repo[: repo.rindex(":")]
        repo = repo.removeprefix("docker.io/").removeprefix("library/")
        for kind, spec in self.services.items():
            if repo in spec.images:
                return kind
        return None

    def clamp(self, cpus: float | None, memory_mb: int | None, timeout_s: int | None) -> Limits:
        d, m = self.limits.default, self.limits.max
        return Limits(
            cpus=min(cpus or d.cpus, m.cpus),
            memory_mb=min(memory_mb or d.memory_mb, m.memory_mb),
            pids=min(d.pids, m.pids),
            timeout_s=min(timeout_s or d.timeout_s, m.timeout_s),
        )


class Env(BaseModel):
    config_file: Path = Path(os.environ.get("SANDBOX_CONFIG", "/app/config/sandbox.yaml"))
    docker_socket: str = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
    workspaces_volume: str = os.environ.get("WORKSPACES_VOLUME", "codewright_workspaces")
    cache_volume: str = os.environ.get("CACHE_VOLUME", "codewright_sandbox-cache")
    cache_dir: Path = Path(os.environ.get("CACHE_DIR", "/cache"))  # the cache volume, mounted in the runner
    state_dir: Path = Path(os.environ.get("STATE_DIR", "/state"))  # shared with the gateway (preview routes)
    gateway_service: str = os.environ.get("GATEWAY_SERVICE", "sandbox-gateway")
    compose_project: str = os.environ.get("COMPOSE_PROJECT", "codewright")
    prefix: str = Field(default=os.environ.get("SANDBOX_PREFIX", "cw-sbx"))
