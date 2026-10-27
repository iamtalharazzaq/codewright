"""Approval gates (README Sections 3.2 and 9.2): approval cards in the chat, implemented with `interrupt()`.

A gate node only builds the card, calls `interrupt()` and records the answer, so re-running it on resume has no side
effects (ADR 0004). Routing reads the latest decision. Edit and Reject send the reviewed step back for rework with
the user's comment in `feedback[step]`.

Tiers decide which standard gates a playbook shows: tier 1 approves the result, tier 2 the plan and the result;
tier 3 playbooks define their own gates.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict, cast

from langgraph.types import interrupt

from agent.playbooks.state import ApprovalRecord, Decision, Node, RunState

GateKind = Literal["plan", "result", "custom"]


@dataclass(frozen=True)
class GateDef:
    id: str
    title: str
    question: str
    reworks: str  # the step that runs again after Edit or Reject
    kind: GateKind = "custom"
    number: int | None = None  # the README's gate number, for playbooks that number them
    summary_keys: tuple[str, ...] = ()  # state keys shown on the card
    subject_key: str | None = None  # state key naming what the gate is about (e.g. the current service)
    # Overrides `reworks` when it depends on the state (e.g. an audit-only branch).
    rework_for: Callable[[Any], str] | None = field(default=None, compare=False)


def plan_gate(reworks: str = "plan") -> GateDef:
    return GateDef(
        "approve_plan", "Approve plan", "Go ahead with this plan?", reworks, kind="plan", summary_keys=("plan",)
    )


def result_gate(reworks: str, summary_keys: tuple[str, ...] = ("steps", "artifacts")) -> GateDef:
    return GateDef(
        "approve_result", "Approve result", "Accept this result?", reworks, kind="result", summary_keys=summary_keys
    )


def gate_applies(kind: GateKind, tier: int) -> bool:
    """Standard gates by tier: result from tier 1, plan from tier 2. Custom gates always apply."""
    if kind == "result":
        return tier >= 1
    if kind == "plan":
        return tier >= 2
    return True


def needs_gate(state: RunState, kind: GateKind) -> bool:
    return gate_applies(kind, state["tier"])


class GatePrompt(TypedDict):
    kind: Literal["gate"]
    gate: str
    number: int | None
    title: str
    question: str
    subject: str | None
    playbook: str
    tier: int
    summary: dict[str, Any]
    options: list[Decision]


class GateAnswer(TypedDict, total=False):
    decision: Decision
    comment: str
    edits: dict[str, Any]


def gate_node[S: RunState](gate: GateDef) -> Node[S]:
    async def node(state: S) -> dict[str, Any]:
        subject = cast(str | None, state.get(gate.subject_key)) if gate.subject_key else None
        prompt: GatePrompt = {
            "kind": "gate",
            "gate": gate.id,
            "number": gate.number,
            "title": gate.title,
            "question": gate.question,
            "subject": subject,
            "playbook": state["playbook"],
            "tier": state["tier"],
            "summary": {k: state.get(k) for k in gate.summary_keys},
            "options": ["approve", "edit", "reject"],
        }
        answer = cast(GateAnswer, interrupt(prompt))
        decision = answer.get("decision")
        if decision not in ("approve", "edit", "reject"):
            raise ValueError(f"Invalid gate decision: {decision!r}")
        record: ApprovalRecord = {
            "gate": gate.id,
            "decision": decision,
            "comment": answer.get("comment", ""),
            "edits": answer.get("edits", {}),
        }
        if subject:
            record["subject"] = subject
        update: dict[str, Any] = {"approvals": [record]}
        if decision != "approve":
            reworked = gate.rework_for(state) if gate.rework_for else gate.reworks
            update["feedback"] = {reworked: record["comment"] or f"{decision} at {gate.title}"}
        return update

    return node


def last_decision(state: RunState, gate_id: str) -> Decision:
    for record in reversed(state.get("approvals", [])):
        if record["gate"] == gate_id:
            decision: Decision = record["decision"]
            return decision
    raise LookupError(f"No decision recorded for {gate_id}")


def after_gate(gate_id: str, approved: str, rework: str) -> Callable[[RunState], str]:
    def route(state: RunState) -> str:
        return approved if last_decision(state, gate_id) == "approve" else rework

    return route
