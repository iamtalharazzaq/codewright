"""GPU-lost handling (README Section 8.1): when the model server is unreachable, checkpoint, pause and ask the user.

The pause is a LangGraph `interrupt()`. Because a node re-runs from the top when resumed, the LLM call is simply tried
again; if it fails again, the next `interrupt()` returns the user's previous answer (interrupts match by index), so the
loop is deterministic. The number of rounds is bounded.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypedDict

from langgraph.types import interrupt

from agent.graph.services import RunServices
from agent.graph.state import WorkflowState
from agent.llm.client import LLMUnavailable

MAX_RECOVERY_ROUNDS = 5

RecoveryChoice = Literal["retry", "switch_to_cpu"]


class LLMUnavailablePrompt(TypedDict):
    kind: Literal["llm_unavailable"]
    step: str
    profile: str
    error: str
    options: list[RecoveryChoice]


class RecoveryAbandoned(Exception):
    pass


async def call_with_recovery(
    state: WorkflowState,
    services: RunServices,
    *,
    step: str,
    task: Callable[[str], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run `task(profile)`; on `LLMUnavailable` pause the run and ask: retry, or switch to the local CPU."""
    profile: str = state["llm_profile"]
    for _ in range(MAX_RECOVERY_ROUNDS):
        try:
            result = await task(profile)
        except LLMUnavailable as exc:
            error = str(exc)
        else:
            # Persist a profile switch so later steps use the CPU too.
            return {**result, "llm_profile": profile} if profile != state["llm_profile"] else result

        # Outside the try block on purpose: interrupt() must never be caught (LangGraph rule).
        await services.emit(state["run_id"], "llm_unavailable", step=step, data={"profile": profile, "error": error})
        options: list[RecoveryChoice] = ["retry"] if profile == "local_cpu" else ["retry", "switch_to_cpu"]
        prompt: LLMUnavailablePrompt = {
            "kind": "llm_unavailable",
            "step": step,
            "profile": profile,
            "error": error,
            "options": options,
        }
        choice = interrupt(prompt)
        if choice == "switch_to_cpu":
            profile = "local_cpu"
    raise RecoveryAbandoned(f"The model server stayed unavailable after {MAX_RECOVERY_ROUNDS} attempts in step {step}")
