"""What a project's own docker-compose file says about running it: the sidecars its app needs and the app's
environment. Works for any project that ships a compose file; nothing here knows a particular project.

Only sidecars whose image is allowed in `config/sandbox.yaml` are kept (Postgres, Redis, MySQL, MongoDB…). `${VAR}`
and `${VAR:-default}` take their default: the host's environment is never read, so no host secret leaks in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from agent.language_packs.base import ServiceNeed, read

COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
CONFIG = Path(__file__).resolve().parents[2] / "config" / "sandbox.yaml"
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


@cache
def allowed_images(config: Path = CONFIG) -> dict[str, str]:
    """image repository → service kind, from config/sandbox.yaml."""
    data = yaml.safe_load(config.read_text(encoding="utf-8")) if config.exists() else {}
    return {image: kind for kind, spec in (data.get("services") or {}).items() for image in spec.get("images", [])}


def repository(image: str) -> str:
    repo = image.split("@", 1)[0]
    if ":" in repo.rsplit("/", 1)[-1]:
        repo = repo[: repo.rindex(":")]
    return repo.removeprefix("docker.io/").removeprefix("library/")


def substitute(value: str) -> str:
    return _VAR.sub(lambda m: m.group(2) or "", value)


def _env(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): substitute("" if v is None else str(v)) for k, v in raw.items()}
    if isinstance(raw, list):
        out: dict[str, str] = {}
        for item in raw:
            key, _, value = str(item).partition("=")
            out[key] = substitute(value)
        return out
    return {}


def _port(raw: Any) -> int | None:
    for item in raw or []:
        text = str(item.get("target") if isinstance(item, dict) else item)
        container = text.rsplit(":", 1)[-1].split("/", maxsplit=1)[0]
        if container.isdigit():
            return int(container)
    return None


@dataclass
class ComposeApp:
    name: str
    context: str  # build context, relative to the project root
    env: dict[str, str] = field(default_factory=dict)
    port: int | None = None
    depends_on: list[str] = field(default_factory=list)


@dataclass
class ComposeFile:
    path: str
    apps: list[ComposeApp] = field(default_factory=list)
    services: list[ServiceNeed] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # images that aren't allowed sidecars


def find(repo: Path, folder: str = ".") -> ComposeFile | None:
    """The compose file in `folder` or, failing that, at the project root."""
    for base in dict.fromkeys([folder, "."]):
        for name in COMPOSE_FILES:
            path = repo / base / name
            if path.is_file():
                return parse(path, repo)
    return None


def parse(path: Path, repo: Path) -> ComposeFile:
    try:
        data = yaml.safe_load(read(path)) or {}
    except yaml.YAMLError:
        data = {}
    base = path.parent
    result = ComposeFile(path=path.relative_to(repo).as_posix())
    allowed = allowed_images()
    for name, svc in (data.get("services") or {}).items():
        if not isinstance(svc, dict):
            continue
        env = _env(svc.get("environment"))
        if "build" in svc:
            build = svc["build"]
            context = build.get("context", ".") if isinstance(build, dict) else str(build)
            ctx = (base / context).resolve()
            try:
                context_rel = ctx.relative_to(repo.resolve()).as_posix() or "."
            except ValueError:
                continue
            depends = svc.get("depends_on") or []
            depends = list(depends) if isinstance(depends, (list, dict)) else []
            result.apps.append(ComposeApp(str(name), context_rel, env, _port(svc.get("ports")), depends))
        elif image := svc.get("image"):
            image = substitute(str(image))
            if repository(image) in allowed:
                result.services.append(ServiceNeed(str(name), image, env))
            else:
                result.skipped.append(image)
    return result


def app_for(compose: ComposeFile | None, component_path: str) -> ComposeApp | None:
    if compose is None:
        return None
    return next((a for a in compose.apps if a.context == component_path), None)
