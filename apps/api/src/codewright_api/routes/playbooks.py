"""Playbooks the harness can run (README Section 5): steps, gates, inputs and default tier, for the UI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.playbooks.registry import Playbook, get_playbook, playbooks

router = APIRouter(prefix="/playbooks", tags=["playbooks"])


class PlaybookOut(BaseModel):
    name: str
    title: str
    description: str
    intent: str | None
    lead_role: str
    tier: int
    steps: list[dict[str, Any]]
    gates: list[dict[str, Any]]
    inputs_schema: dict[str, Any]


def playbook_out(pb: Playbook) -> PlaybookOut:
    return PlaybookOut(
        name=pb.name,
        title=pb.title,
        description=pb.description,
        intent=pb.intent,
        lead_role=pb.lead_role,
        tier=pb.tier,
        steps=[{"id": s.id, "title": s.title, "role": s.role, "number": s.number} for s in pb.spec.steps],
        gates=[
            {"id": g.id, "title": g.title, "kind": g.kind, "number": g.number, "reworks": g.reworks}
            for g in pb.spec.gates
        ],
        inputs_schema=pb.spec.inputs.model_json_schema(),
    )


@router.get("")
async def list_playbooks() -> list[PlaybookOut]:
    return [playbook_out(pb) for pb in playbooks().values()]


@router.get("/{name}")
async def get_one(name: str) -> PlaybookOut:
    try:
        return playbook_out(get_playbook(name))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
