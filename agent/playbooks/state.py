"""Run state shared by every playbook (README Section 9.1).

A playbook's own state extends `RunState` with its fields. Everything is checkpointed in Postgres, so it must stay
JSON-serializable. Fields written by several nodes use reducers (append or merge) so updates never overwrite each other.
"""

from __future__ import annotations

import operator
from collections.abc import Awaitable
from typing import Annotated, Any, Literal, NotRequired, Protocol, TypedDict

from agent.llm.config import ProfileName

Decision = Literal["approve", "edit", "reject"]
PlanStatus = Literal["pending", "in_progress", "done", "skipped"]
ArtifactKind = Literal["plan", "diff", "graph", "diagram", "tests", "preview", "report", "file"]


def merge[V](a: dict[str, V], b: dict[str, V]) -> dict[str, V]:
    return {**a, **b}


class PlanItem(TypedDict):
    id: str
    title: str
    role: str
    status: PlanStatus


class StepResult(TypedDict, total=False):
    status: Literal["done", "failed", "skipped"]
    summary: str
    subject: str


class ArtifactRef(TypedDict):
    """Something the side panel can show (README Section 2.2). `path` is relative to the run's workspace."""

    kind: ArtifactKind
    title: str
    path: str
    step: str


class ApprovalRecord(TypedDict):
    gate: str
    decision: Decision
    comment: str
    edits: dict[str, Any]
    subject: NotRequired[str]


class ErrorRecord(TypedDict):
    step: str
    message: str


class Usage(TypedDict):
    llm_calls: int
    tokens: int


class BudgetLimits(TypedDict):
    """Resolved from config/budgets.yaml for the run's tier when the run is created (see agent/llm/budgets.py)."""

    step_max_tokens: int
    step_max_llm_calls: int
    run_max_tokens: int
    run_max_hours: float


class BudgetState(TypedDict):
    run: Usage
    steps: dict[str, Usage]
    # Each "continue" after a limit was hit raises every limit by another 100% of its base value.
    extensions: int


def add_budget(a: BudgetState, b: BudgetState) -> BudgetState:
    """Sum usage; updates carry only what a node used (deltas). LangGraph starts the channel at `{}`."""
    a = {**empty_budget(), **a}
    b = {**empty_budget(), **b}
    steps = dict(a["steps"])
    for name, used in b["steps"].items():
        old = steps.get(name, {"llm_calls": 0, "tokens": 0})
        steps[name] = {"llm_calls": old["llm_calls"] + used["llm_calls"], "tokens": old["tokens"] + used["tokens"]}
    return {
        "run": {
            "llm_calls": a["run"]["llm_calls"] + b["run"]["llm_calls"],
            "tokens": a["run"]["tokens"] + b["run"]["tokens"],
        },
        "steps": steps,
        "extensions": a["extensions"] + b["extensions"],
    }


def add_artifacts(a: list[ArtifactRef], b: list[ArtifactRef]) -> list[ArtifactRef]:
    """Append, replacing an artifact with the same path (a reworked step rewrites its file)."""
    paths = {x["path"] for x in b}
    return [x for x in a if x["path"] not in paths] + b


def empty_budget() -> BudgetState:
    return {"run": {"llm_calls": 0, "tokens": 0}, "steps": {}, "extensions": 0}


class RunState(TypedDict):
    run_id: str
    project_id: str | None
    playbook: str
    tier: int  # 0-3 (README Section 3.2); the user may raise it, never lower it
    inputs: dict[str, Any]  # validated by the playbook's input model
    workspace: str  # absolute path; agents read and write files only below it
    llm_profile: ProfileName
    started_at: float  # unix time, for the run time budget
    limits: BudgetLimits

    plan: NotRequired[list[PlanItem]]  # the live checklist; a node replaces it with the updated list
    steps: NotRequired[Annotated[dict[str, StepResult], merge]]
    artifacts: NotRequired[Annotated[list[ArtifactRef], add_artifacts]]
    # Appended by every gate; the latest decision drives routing.
    approvals: NotRequired[Annotated[list[ApprovalRecord], operator.add]]
    # Comments from Edit/Reject, keyed by step, read by the step when it reworks.
    feedback: NotRequired[Annotated[dict[str, str], merge]]
    verification: NotRequired[dict[str, Any] | None]
    delivery: NotRequired[list[dict[str, Any]]]
    budget: NotRequired[Annotated[BudgetState, add_budget]]
    errors: NotRequired[Annotated[list[ErrorRecord], operator.add]]


class Node[S](Protocol):
    """A playbook node. The parameter must be called `state` to match LangGraph's node protocol."""

    def __call__(self, state: S) -> Awaitable[dict[str, Any]]: ...
