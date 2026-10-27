from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from agent.llm.budgets import limits_for_tier
from agent.playbooks.plan import plan_from
from agent.playbooks.registry import get_playbook
from agent.playbooks.services import RunServices
from agent.playbooks.state import RunState, empty_budget

Answer = Any


def compiled(
    playbook: str, services: RunServices, saver: BaseCheckpointSaver[Any] | None = None
) -> CompiledStateGraph[Any, Any, Any, Any]:
    return get_playbook(playbook).spec.build(services).compile(checkpointer=saver or InMemorySaver())


def initial_state(playbook: str, tmp_path: Path, *, tier: int | None = None, **inputs: Any) -> RunState:
    """The state the run manager starts a run with (inputs validated, defaults filled in)."""
    pb = get_playbook(playbook)
    validated = pb.spec.inputs.model_validate({"stub_delay_s": 0, **inputs}).model_dump(mode="json")
    tier = max(pb.tier, pb.spec.min_tier(validated)) if tier is None else tier
    return {
        "run_id": "r1",
        "project_id": "p1",
        "playbook": playbook,
        "tier": tier,
        "inputs": validated,
        "workspace": str(tmp_path),
        "llm_profile": "remote_gpu",
        "started_at": time.time(),
        "limits": limits_for_tier(tier),
        "plan": plan_from(pb.spec.initial_plan(validated)),
        "budget": empty_budget(),
    }


def cfg(thread: str = "t1") -> RunnableConfig:
    return {"configurable": {"thread_id": thread}}


async def drive(
    graph: CompiledStateGraph[Any, Any, Any, Any],
    config: RunnableConfig,
    first_input: Any,
    answer: Callable[[dict[str, Any]], Answer],
    max_steps: int = 50,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run until the graph finishes, answering every interrupt with `answer(prompt)`. Returns (state, prompts)."""
    prompts: list[dict[str, Any]] = []
    result = await graph.ainvoke(first_input, config)
    for _ in range(max_steps):
        interrupts = result.get("__interrupt__") or []
        if not interrupts:
            return result, prompts
        prompt = interrupts[0].value
        prompts.append(prompt)
        result = await graph.ainvoke(Command(resume=answer(prompt)), config)
    raise AssertionError("workflow did not finish")


def approve_all(prompt: dict[str, Any]) -> Answer:
    return {"decision": "approve"}


def gates_of(prompts: Sequence[dict[str, Any]]) -> list[str]:
    return [p["gate"] + (f":{p['subject']}" if p.get("subject") else "") for p in prompts if p["kind"] == "gate"]


def started(events: Sequence[tuple[str, str | None, dict[str, Any]]]) -> list[str | None]:
    return [step for (event, step, _) in events if event == "step_started"]
