"""The workflow steps (README Section 2) and their Phase 1 stub implementations.

Each stub announces itself, waits `stub_delay_s` (so pause/kill/resume can be tested), writes a marker file into the
project workspace and returns placeholder state. Later phases replace one stub at a time with the real step.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent.graph.llm_recovery import call_with_recovery
from agent.graph.services import RunServices
from agent.graph.state import Node, WorkflowState
from agent.llm.structured import structured


@dataclass(frozen=True)
class StepDef:
    id: str
    title: str
    role: str  # lead role (README Section 4.1)
    number: int | None  # README step number; None for the audit report and delivery


STEPS: dict[str, StepDef] = {
    s.id: s
    for s in [
        StepDef("intake", "Intake", "business_analyst", 1),
        StepDef("baseline", "Baseline", "qa_engineer", 2),
        StepDef("as_is", "As-Is architecture", "solution_architect", 3),
        StepDef("to_be", "To-Be architecture", "solution_architect", 4),
        StepDef("languages", "Language per service", "solution_architect", 5),
        StepDef("audit_report", "Audit report", "technical_writer", None),
        StepDef("foundation", "Foundation", "devops_engineer", 6),
        StepDef("build_service", "Build service", "backend_developer", 7),
        StepDef("db_split", "Database split", "database_engineer", 8),
        StepDef("frontend", "One frontend + modern UI", "frontend_developer", 9),
        StepDef("report", "Report", "technical_writer", 10),
        StepDef("deliver", "Deliver", "release_manager", None),
    ]
}

# GoShop's least-coupled-first order (README Step 7), used as the stub To-Be design.
STUB_SERVICES = ["notification", "payment", "user", "catalog", "order"]


class IntakeSummary(BaseModel):
    """Phase 1's single real LLM task, used to exercise the LLM path (structured output, tracing, GPU-lost pause)."""

    summary: str = Field(description="One or two sentences.")
    next_step: str = Field(description="What Codewright does next, in a few words.")


def _stub_output(step: str, state: WorkflowState) -> dict[str, Any]:  # noqa: PLR0911  (one branch per step)
    if step == "intake":
        return {"stack": {"stub": True}, "goals": {"stub": True}}
    if step == "baseline":
        return {"baseline": {"stub": True, "confidence": "static-only"}}
    if step == "as_is":
        return {"as_is": {"stub": True}}
    if step == "to_be":
        services = state.get("options", {}).get("services", STUB_SERVICES[:2])
        return {"to_be": {"stub": True, "services": services}, "service_queue": list(services)}
    if step == "languages":
        return {"language_plan": {s: {"language": "go", "mode": "extract"} for s in state.get("service_queue", [])}}
    if step == "db_split":
        return {"db_split_stage": 7}
    if step == "frontend":
        return {"frontend_status": {"stub": True}}
    if step in ("report", "audit_report"):
        return {"report": {"stub": True, "kind": step}}
    return {}


def stub_step(step: str, services: RunServices) -> Node:
    definition = STEPS[step]

    async def node(state: WorkflowState) -> dict[str, Any]:
        run_id = state["run_id"]
        subject = state.get("current_service") if step == "build_service" else None
        await services.emit(run_id, "step_started", step=step, data={"role": definition.role, "subject": subject})

        update = _stub_output(step, state)
        if step == "intake" and state.get("options", {}).get("use_llm"):
            update.update(await _intake_with_llm(state, services))

        await asyncio.sleep(float(state.get("options", {}).get("stub_delay_s", 1.0)))
        _write_marker(Path(state["workspace"]), step, subject, state.get("feedback", {}).get(step))

        if step == "build_service" and subject:
            update["service_results"] = {subject: {"status": "built", "stub": True}}
        await services.emit(run_id, "step_completed", step=step, data={"role": definition.role, "subject": subject})
        return {**update, "completed_steps": [f"{step}:{subject}" if subject else step]}

    return node


async def _intake_with_llm(state: WorkflowState, services: RunServices) -> dict[str, Any]:
    async def task(profile: str) -> dict[str, Any]:
        client = services.llm(profile, run_id=state["run_id"], step="intake", role="business_analyst")  # type: ignore[arg-type]
        result = await structured(
            client,
            IntakeSummary,
            [
                {"role": "system", "content": "You are the Business Analyst of Codewright. Answer in JSON only."},
                {
                    "role": "user",
                    "content": f"A new {state['mode']} project was created. Summarize what intake will check "
                    "(languages, frameworks, database, goals, delivery) and name the next step.",
                },
            ],
            task="intake_summary",
            max_tokens=200,
        )
        return {"goals": {"stub": True, "llm_summary": result.value.model_dump()}}

    return await call_with_recovery(state, services, step="intake", task=task)


def _write_marker(workspace: Path, step: str, subject: str | None, feedback: str | None) -> None:
    folder = workspace / "stub" / step
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{subject}.md" if subject else "STUB.md"
    lines = [f"# {STEPS[step].title} (stub)", "", "Written by the Phase 1 workflow skeleton."]
    if feedback:
        lines += ["", f"Reworked after feedback: {feedback}"]
    (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
