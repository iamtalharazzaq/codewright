"""The template library (CODEWRIGHT.md Section 8.4): `templates/apps/<name>/` with a `manifest.yaml`.

A template is copied as is, with `__name__`-style placeholders filled in file contents and paths. Every template
ships with tests, a `GUIDE.md` skeleton and the Graphify setup (`GRAPHIFY.md`, an MCP config example, a CI step
that rebuilds the graph).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent.language_packs.base import ServiceSpec, fill, template_values

ROOT = Path(__file__).resolve().parents[2] / "templates"
KINDS = ("apps", "services")
SKIP = {"node_modules", ".venv", "__pycache__", ".codewright", "graphify-out", "build", "dist"}
BINARY = {".png", ".ico", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2"}


@dataclass
class Template:
    name: str
    path: Path
    language: str
    pack: str
    stack: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    extension_points: list[str] = field(default_factory=list)
    run: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "path"}


def load(path: Path) -> Template:
    data = yaml.safe_load((path / "manifest.yaml").read_text(encoding="utf-8")) or {}
    return Template(
        name=data.get("name", path.name),
        path=path,
        language=data["language"],
        pack=data["pack"],
        stack=data.get("stack", []),
        features=data.get("features", []),
        extension_points=data.get("extension_points", []),
        run=data.get("run", {}),
        description=data.get("description", ""),
    )


def available(root: Path = ROOT) -> list[Template]:
    found = []
    for kind in KINDS:
        for path in sorted((root / kind).glob("*/manifest.yaml")):
            found.append(load(path.parent))
    return found


def get(name: str, root: Path = ROOT) -> Template:
    for t in available(root):
        if t.name == name:
            return t
    raise KeyError(f"no template named {name!r}")


def scaffold(spec: ServiceSpec, out: Path, root: Path = ROOT) -> Template:
    """Copy template `spec.template` into `out` (which must be empty or missing), filling the placeholders."""
    template = get(spec.template, root)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} isn't empty")
    values = template_values(spec)
    for src in sorted(template.path.rglob("*")):
        relative = src.relative_to(template.path)
        if any(part in SKIP for part in relative.parts) or src.name == "manifest.yaml":
            continue
        target = out / fill(relative.as_posix(), values).replace(".tmpl", "")
        if src.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in BINARY:
            shutil.copyfile(src, target)
        else:
            target.write_text(fill(src.read_text(encoding="utf-8"), values), encoding="utf-8")
        target.chmod(src.stat().st_mode & 0o777)
    return template
