from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

Answer = Any


def initial_state(tmp_path: Path, mode: str = "audit", **options: Any) -> dict[str, Any]:
    return {
        "project_id": "p1",
        "run_id": "r1",
        "mode": mode,
        "workspace": str(tmp_path),
        "llm_profile": "remote_gpu",
        "options": {"stub_delay_s": 0, **options},
    }


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
