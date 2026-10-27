"""The 8 approval gates (README Section 2.1). A gate node only calls `interrupt()` and records the answer, so re-running
it on resume has no side effects (ADR 0004). Routing reads the latest approval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast

from langgraph.types import interrupt

from agent.graph.state import ApprovalRecord, Decision, Node, WorkflowState


@dataclass(frozen=True)
class GateDef:
    id: str
    number: int
    title: str
    reworks: str  # the step that runs again after Edit or Reject
    question: str


GATES: dict[str, GateDef] = {
    g.id: g
    for g in [
        GateDef("gate1", 1, "Confirm goals", "intake", "Is the detected stack right, and are these your goals?"),
        GateDef("gate2", 2, "Confirm As-Is", "as_is", "Does this match how your system works today?"),
        GateDef("gate3", 3, "Approve design", "to_be", "Approve these services and boundaries?"),
        GateDef("gate4", 4, "Pick languages", "languages", "Approve the language for each service?"),
        GateDef("gate5", 5, "Approve service PR", "build_service", "Approve this service's PR and cut-over?"),
        GateDef("gate6", 6, "Approve database split", "db_split", "Approve the migration and rollback scripts?"),
        GateDef("gate7", 7, "Approve UI", "frontend", "Approve the new frontend?"),
        GateDef("gate8", 8, "Choose delivery", "report", "Where should the result be delivered?"),
    ]
}


class GatePrompt(TypedDict):
    kind: Literal["gate"]
    gate: str
    number: int
    title: str
    question: str
    subject: str | None
    summary: dict[str, Any]
    options: list[Decision]


class GateAnswer(TypedDict, total=False):
    decision: Decision
    comment: str
    edits: dict[str, Any]


def _summary(gate: GateDef, state: WorkflowState) -> dict[str, Any]:
    """What the gate card shows: the state the decision is about (stub data in Phase 1)."""
    keys = {
        "gate1": ("stack", "goals"),
        "gate2": ("as_is",),
        "gate3": ("to_be",),
        "gate4": ("language_plan",),
        "gate5": ("service_results",),
        "gate6": ("db_split_stage",),
        "gate7": ("frontend_status",),
        "gate8": ("report", "delivery"),
    }[gate.id]
    return {k: state.get(k) for k in keys}


def gate_node(gate_id: str) -> Node:
    gate = GATES[gate_id]

    async def node(state: WorkflowState) -> dict[str, Any]:
        subject = state.get("current_service") if gate_id == "gate5" else None
        prompt: GatePrompt = {
            "kind": "gate",
            "gate": gate.id,
            "number": gate.number,
            "title": gate.title,
            "question": gate.question,
            "subject": subject,
            "summary": _summary(gate, state),
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
            reworked = "audit_report" if gate_id == "gate8" and state["mode"] == "audit" else gate.reworks
            update["feedback"] = {reworked: record["comment"] or f"{decision} at {gate.title}"}
        return update

    return node


def last_decision(state: WorkflowState, gate_id: str) -> Decision:
    for record in reversed(state.get("approvals", [])):
        if record["gate"] == gate_id:
            decision: Decision = record["decision"]
            return decision
    raise LookupError(f"No decision recorded for {gate_id}")
