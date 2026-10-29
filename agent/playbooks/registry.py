"""Playbook registry (README Section 5 and Section 7, component 3).

Each playbook lives in `agent/playbooks/<name>/` with a `config.yaml` (title, intent, lead role, tier) and a
`graph.py` exposing `PLAYBOOK_SPEC`: its input model, steps, gates, timeline and graph builder. Adding a playbook means
adding a folder and one line in `_MODULES`; the run manager, API and UI work from the registry.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from langgraph.graph import StateGraph
from pydantic import BaseModel

from agent.playbooks.gates import GateDef
from agent.playbooks.services import RunServices

PLAYBOOKS_DIR = Path(__file__).resolve().parent
TIERS_FILE = PLAYBOOKS_DIR.parents[1] / "config" / "tiers.yaml"

# Playbooks with a runnable graph so far. Later phases add one per intent (config/tiers.yaml).
_MODULES = (
    "sample",
    "architecture_change",
    "code_review",
    "audit",
    "docs",
    "write_code",
    "bug_fix",
    "tests",
    "refactor",
    "performance",
    "security",
    "upgrade",
    "db_change",
    "feature",
    "frontend",
    "devops",
    "new_app",
)


@dataclass(frozen=True)
class StepDef:
    id: str
    title: str
    role: str  # lead role for this step (README Section 6.2)
    number: int | None = None  # the README's step number, for playbooks that number them


@dataclass(frozen=True)
class PlaybookSpec:
    """What a playbook's `graph.py` provides."""

    inputs: type[BaseModel]
    steps: tuple[StepDef, ...]
    gates: tuple[GateDef, ...]
    build: Callable[[RunServices], StateGraph[Any, Any, Any, Any]]
    # The ordered node ids the timeline shows for these inputs (branches differ, e.g. audit vs conversion).
    flow: Callable[[dict[str, Any]], list[str]]
    # The checklist a run starts with, as (id, title, role); empty when a planning step writes it.
    initial_plan: Callable[[dict[str, Any]], list[tuple[str, str, str]]] = lambda _inputs: []
    # The tier these inputs need when it's above the playbook's default (e.g. a microservices target is tier 3).
    min_tier: Callable[[dict[str, Any]], int] = lambda _inputs: 0
    # Playbooks that read or change a project's code need one (the run's workspace is the project's).
    needs_project: bool = False


@dataclass(frozen=True)
class Playbook:
    name: str
    title: str
    description: str
    intent: str | None
    lead_role: str
    tier: int
    spec: PlaybookSpec


def _tiers() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(TIERS_FILE.read_text(encoding="utf-8"))
    return data


def _load(name: str) -> Playbook:
    config = yaml.safe_load((PLAYBOOKS_DIR / name / "config.yaml").read_text(encoding="utf-8"))
    module = importlib.import_module(f"agent.playbooks.{name}.graph")
    intent = config.get("intent")
    tier = config.get("tier")
    if tier is None:  # the intent's default tier (README Section 4)
        tier = _tiers()["intents"][intent]["tier"]
    return Playbook(
        name=name,
        title=config["title"],
        description=config["description"],
        intent=intent,
        lead_role=config["lead_role"],
        tier=int(tier),
        spec=module.PLAYBOOK_SPEC,
    )


@cache
def playbooks() -> dict[str, Playbook]:
    return {name: _load(name) for name in _MODULES}


def get_playbook(name: str) -> Playbook:
    try:
        return playbooks()[name]
    except KeyError:
        raise LookupError(f"Unknown playbook {name!r}. Available: {', '.join(playbooks())}") from None
