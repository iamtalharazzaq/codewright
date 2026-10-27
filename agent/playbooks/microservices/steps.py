"""Microservices playbook steps (README Section 5.18) and their stub implementations.

Each stub announces itself, waits `stub_delay_s` (so pause/kill/resume can be tested), writes a marker file into the
workspace and returns placeholder state. Phases 15-17 replace one stub at a time with the real step.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any, Literal, NotRequired

from pydantic import BaseModel, Field

from agent.llm.config import ProfileName
from agent.llm.structured import structured
from agent.playbooks.llm_step import TaskResult, llm_step
from agent.playbooks.plan import mark
from agent.playbooks.registry import StepDef
from agent.playbooks.services import RunServices
from agent.playbooks.state import Node, RunState, merge


class MicroservicesInputs(BaseModel):
    mode: Literal["conversion", "audit"] = Field(
        title="Mode", default="audit", description="conversion: all 10 steps; audit: steps 1-5, report, delivery."
    )
    services: list[str] = Field(title="Services", default_factory=lambda: ["notification", "payment"], max_length=10)
    stub_delay_s: float = Field(
        default=2.0, ge=0, le=60, title="Seconds per stub step", description="How long each stub step takes."
    )
    use_llm: bool = Field(default=False, title="Use the model", description="Make one real LLM call at intake.")


class MicroservicesState(RunState):
    stack: NotRequired[dict[str, Any]]
    goals: NotRequired[dict[str, Any]]
    baseline: NotRequired[dict[str, Any]]
    as_is: NotRequired[dict[str, Any]]
    to_be: NotRequired[dict[str, Any]]
    language_plan: NotRequired[dict[str, Any]]
    service_queue: NotRequired[list[str]]
    current_service: NotRequired[str | None]
    service_results: NotRequired[Annotated[dict[str, Any], merge]]
    db_split_stage: NotRequired[int]
    frontend_status: NotRequired[dict[str, Any]]
    report: NotRequired[dict[str, Any]]


STEPS: dict[str, StepDef] = {
    s.id: s
    for s in [
        StepDef("intake", "Intake", "business_analyst", 1),
        StepDef("baseline", "Baseline", "qa_engineer", 2),
        StepDef("as_is", "As-Is architecture", "solution_architect", 3),
        StepDef("to_be", "To-Be architecture", "solution_architect", 4),
        StepDef("languages", "Language per service", "solution_architect", 5),
        StepDef("audit_report", "Audit report", "technical_writer"),
        StepDef("foundation", "Foundation", "devops_engineer", 6),
        StepDef("build_service", "Build service", "backend_developer", 7),
        StepDef("db_split", "Database split", "database_engineer", 8),
        StepDef("frontend", "One frontend + modern UI", "frontend_developer", 9),
        StepDef("report", "Report", "technical_writer", 10),
        StepDef("deliver", "Deliver", "release_manager"),
    ]
}


class IntakeSummary(BaseModel):
    """The playbook's single real LLM task so far, to exercise the LLM path (structured output, traces, recovery)."""

    summary: str = Field(description="One or two sentences.")
    next_step: str = Field(description="What Codewright does next, in a few words.")


def _stub_output(step: str, state: MicroservicesState) -> dict[str, Any]:  # noqa: PLR0911  (one branch per step)
    if step == "intake":
        return {"stack": {"stub": True}, "goals": {"stub": True}}
    if step == "baseline":
        return {"baseline": {"stub": True, "confidence": "static-only"}}
    if step == "as_is":
        return {"as_is": {"stub": True}}
    if step == "to_be":
        services = list(state["inputs"].get("services") or [])
        return {"to_be": {"stub": True, "services": services}, "service_queue": services}
    if step == "languages":
        return {"language_plan": {s: {"language": "go", "mode": "extract"} for s in state.get("service_queue", [])}}
    if step == "db_split":
        return {"db_split_stage": 7}
    if step == "frontend":
        return {"frontend_status": {"stub": True}}
    if step in ("report", "audit_report"):
        return {"report": {"stub": True, "kind": step}}
    return {}


def stub_step(step: str, services: RunServices) -> Node[MicroservicesState]:
    definition = STEPS[step]

    async def node(state: MicroservicesState) -> dict[str, Any]:
        run_id = state["run_id"]
        subject = state.get("current_service") if step == "build_service" else None
        await services.emit(run_id, "step_started", step=step, data={"role": definition.role, "subject": subject})

        update = _stub_output(step, state)
        if step == "intake" and state["inputs"].get("use_llm"):
            update.update(await _intake_with_llm(state, services))

        await asyncio.sleep(float(state["inputs"].get("stub_delay_s", 1.0)))
        _write_marker(Path(state["workspace"]), step, subject, state.get("feedback", {}).get(step))

        if step == "build_service" and subject:
            update["service_results"] = {subject: {"status": "built", "stub": True}}
        plan = state.get("plan", [])
        if step != "build_service" or not state.get("service_queue"):  # the last service finishes the step
            plan = mark(plan, step, "done")
        await services.emit(run_id, "step_completed", step=step, data={"role": definition.role, "subject": subject})
        key = f"{step}:{subject}" if subject else step
        result: dict[str, Any] = {"status": "done", "summary": f"{definition.title} (stub)"}
        if subject:
            result["subject"] = subject
        return {**update, "plan": plan, "steps": {key: result}}

    return node


async def _intake_with_llm(state: MicroservicesState, services: RunServices) -> dict[str, Any]:
    async def task(profile: ProfileName) -> TaskResult:
        client = services.llm(profile, run_id=state["run_id"], step="intake", role="business_analyst")
        result = await structured(
            client,
            IntakeSummary,
            [
                {"role": "system", "content": "You are the Business Analyst of Codewright. Answer in JSON only."},
                {
                    "role": "user",
                    "content": f"A new {state['inputs'].get('mode')} microservices project was created. Summarize "
                    "what intake will check (languages, frameworks, database, goals, delivery) and name the next step.",
                },
            ],
            task="intake_summary",
            max_tokens=200,
        )
        goals = {"stub": True, "llm_summary": result.value.model_dump()}
        return TaskResult({"goals": goals}, len(result.attempts), result.usage.total_tokens)

    return await llm_step(state, services, step="intake", task=task)


def _write_marker(workspace: Path, step: str, subject: str | None, feedback: str | None) -> None:
    folder = workspace / "stub" / step
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{subject}.md" if subject else "STUB.md"
    lines = [f"# {STEPS[step].title} (stub)", "", "Written by the microservices playbook skeleton."]
    if feedback:
        lines += ["", f"Reworked after feedback: {feedback}"]
    (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
