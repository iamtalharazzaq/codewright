"""Running an LLM task inside a playbook node: budgets, GPU-loss recovery and usage accounting.

Two things can pause a run here, both as LangGraph `interrupt()`s so the run is checkpointed and resumable:
- a **budget** limit is reached (README Section 9.2): ask to continue (limits grow) or stop;
- the **model server is unavailable** (README Section 10): ask to retry or switch to the local CPU.

A node re-runs from the top when resumed, and interrupts match by index, so the sequence of prompts is deterministic.
The interrupts are outside every `try` block on purpose: `interrupt()` must never be caught.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langgraph.types import interrupt

from agent.llm.budgets import exceeded
from agent.llm.client import LLMUnavailable
from agent.llm.config import ProfileName
from agent.playbooks.services import RunServices
from agent.playbooks.state import BudgetState, RunState

MAX_RECOVERY_ROUNDS = 5

RecoveryChoice = Literal["retry", "switch_to_cpu"]
BudgetChoice = Literal["continue", "stop"]


class LLMUnavailablePrompt(TypedDict):
    kind: Literal["llm_unavailable"]
    step: str
    profile: str
    error: str
    options: list[RecoveryChoice]


class BudgetPrompt(TypedDict):
    kind: Literal["budget_exceeded"]
    step: str
    reason: str
    used: dict[str, Any]
    options: list[BudgetChoice]


class RecoveryAbandoned(Exception):
    pass


class RunStopped(Exception):
    """The user chose to stop the run (e.g. at a budget prompt)."""


@dataclass(frozen=True)
class TaskResult:
    update: dict[str, Any]
    llm_calls: int
    tokens: int


async def llm_step(
    state: RunState,
    services: RunServices,
    *,
    step: str,
    task: Callable[[ProfileName], Awaitable[TaskResult]],
) -> dict[str, Any]:
    """Run `task(profile)` within the run's budget; pause and ask when a limit is hit or the model server is gone.

    Returns the task's state update plus the usage (for the budget reducer) and the profile, if the user switched."""
    budget: BudgetState = state["budget"]
    extensions = 0
    reason = exceeded(state["limits"], budget, step, state["started_at"])
    if reason:
        await services.emit(state["run_id"], "budget_exceeded", step=step, data={"reason": reason})
        prompt: BudgetPrompt = {
            "kind": "budget_exceeded",
            "step": step,
            "reason": reason,
            "used": {"run": budget["run"], "step": budget["steps"].get(step)},
            "options": ["continue", "stop"],
        }
        if interrupt(prompt) == "stop":
            raise RunStopped(f"Stopped by the user at the budget limit in step {step}: {reason}")
        extensions = 1

    profile: ProfileName = state["llm_profile"]
    for _ in range(MAX_RECOVERY_ROUNDS):
        try:
            result = await task(profile)
        except LLMUnavailable as exc:
            error = str(exc)
        else:
            used: BudgetState = {
                "run": {"llm_calls": result.llm_calls, "tokens": result.tokens},
                "steps": {step: {"llm_calls": result.llm_calls, "tokens": result.tokens}},
                "extensions": extensions,
            }
            update = {**result.update, "budget": used}
            if profile != state["llm_profile"]:
                update["llm_profile"] = profile  # later steps use the CPU too
            return update

        await services.emit(state["run_id"], "llm_unavailable", step=step, data={"profile": profile, "error": error})
        options: list[RecoveryChoice] = ["retry"] if profile == "local_cpu" else ["retry", "switch_to_cpu"]
        recovery: LLMUnavailablePrompt = {
            "kind": "llm_unavailable",
            "step": step,
            "profile": profile,
            "error": error,
            "options": options,
        }
        if interrupt(recovery) == "switch_to_cpu":
            profile = "local_cpu"
    raise RecoveryAbandoned(f"The model server stayed unavailable after {MAX_RECOVERY_ROUNDS} attempts in step {step}")
