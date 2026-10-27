"""Workflow state (README Section 7.1).

Phase 1 keeps the fields as plain JSON-able dicts; later phases replace the `dict[str, Any]` fields with typed models
as each step gets real content. Everything here is checkpointed in Postgres, so it must stay JSON-serializable.
"""

from __future__ import annotations

import operator
from collections.abc import Awaitable
from typing import Annotated, Any, Literal, NotRequired, Protocol, TypedDict

Mode = Literal["conversion", "audit"]
Decision = Literal["approve", "edit", "reject"]


class ApprovalRecord(TypedDict):
    gate: str
    decision: Decision
    comment: str
    edits: dict[str, Any]
    subject: NotRequired[str]  # e.g. the service name for Gate 5


class ErrorRecord(TypedDict):
    step: str
    message: str


class MonoShiftState(TypedDict):
    project_id: str
    run_id: str
    mode: Mode
    workspace: str
    llm_profile: Literal["remote_gpu", "local_cpu"]
    options: dict[str, Any]  # run options, e.g. {"use_llm": False, "stub_delay_s": 1.0}

    source: NotRequired[dict[str, Any]]
    stack: NotRequired[dict[str, Any]]
    goals: NotRequired[dict[str, Any]]
    delivery: NotRequired[list[dict[str, Any]]]
    baseline: NotRequired[dict[str, Any]]
    graph_refs: NotRequired[dict[str, Any]]
    as_is: NotRequired[dict[str, Any]]
    to_be: NotRequired[dict[str, Any]]
    language_plan: NotRequired[dict[str, Any]]
    service_queue: NotRequired[list[str]]
    current_service: NotRequired[str | None]
    service_results: NotRequired[Annotated[dict[str, Any], lambda a, b: {**a, **b}]]
    db_split_stage: NotRequired[int]
    frontend_status: NotRequired[dict[str, Any]]
    report: NotRequired[dict[str, Any]]

    # Appended by every gate; the latest decision drives routing.
    approvals: NotRequired[Annotated[list[ApprovalRecord], operator.add]]
    # Comments from Edit/Reject, keyed by step, read by the step when it reworks.
    feedback: NotRequired[Annotated[dict[str, str], lambda a, b: {**a, **b}]]
    completed_steps: NotRequired[Annotated[list[str], operator.add]]
    errors: NotRequired[Annotated[list[ErrorRecord], operator.add]]


class Node(Protocol):
    """A workflow node. The parameter must be called `state` to match LangGraph's node protocol."""

    def __call__(self, state: MonoShiftState) -> Awaitable[dict[str, Any]]: ...
