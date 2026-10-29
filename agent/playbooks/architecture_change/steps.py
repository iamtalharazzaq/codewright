"""Architecture-change inputs, state and steps (CODEWRIGHT.md Section 5.18).

The real steps live in `design.py` (Phase 15: design for every target, conversion to clean modules and a modular
monolith). What is left here are the stubs of the microservices conversion (`simulate`, Phases 16-17): each announces
itself, waits `stub_delay_s` (so pause/kill/resume can be tested), writes a marker file into the workspace and returns
placeholder state. Phases 16-17 replace them one at a time.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any, Literal, NotRequired

from pydantic import BaseModel, Field, model_validator

from agent.llm.config import ProfileName
from agent.llm.structured import structured
from agent.playbooks.llm_step import TaskResult, llm_step
from agent.playbooks.plan import mark
from agent.playbooks.registry import StepDef
from agent.playbooks.services import RunServices
from agent.playbooks.state import Node, RunState, merge

Target = Literal["recommend", "microservices", "modules", "modular_monolith", "merge", "serverless", "event_driven"]
DESIGN_TARGETS = ("recommend", "modules", "modular_monolith", "microservices", "merge", "serverless", "event_driven")
# Phase 17: merge is a real, mechanical fold-back; serverless packages stateless parts; event_driven wires the bus
# and the safe half of each subscription. All seven targets can be designed; these six can be converted for real.
CONVERT_TARGETS = ("modules", "modular_monolith", "microservices", "merge", "serverless", "event_driven")


class MicroservicesInputs(BaseModel):
    target: Target = Field(
        title="Target architecture",
        default="microservices",
        description="Clean modules, modular monolith, microservices, merge services, serverless or event-driven; or "
        "'recommend' to get the simplest architecture that fits.",
        json_schema_extra={"x-available": list(DESIGN_TARGETS)},
    )
    mode: Literal["conversion", "audit"] = Field(
        title="Mode",
        default="audit",
        description="Audit: analyse and design, change nothing. Conversion: also change the code (clean modules, "
        "modular monolith, microservices).",
    )
    request: str = Field(
        default="",
        title="Goals",
        max_length=4000,
        description="What you want from the change (scale, cost, cleaner code).",
    )
    allowed_languages: list[str] = Field(
        default_factory=list, title="Languages allowed for services", description="Empty: the five supported languages."
    )
    services: list[str] = Field(
        title="Services",
        default_factory=lambda: ["notification", "payment"],
        max_length=10,
        json_schema_extra={"x-advanced": True},
    )
    # Test knobs. Hidden in the UI (x-advanced).
    simulate: bool = Field(
        default=False,
        title="Simulate",
        description="Run the stub steps of the microservices conversion (no project).",
        json_schema_extra={"x-advanced": True},
    )
    stub_delay_s: float = Field(default=2.0, ge=0, le=60, json_schema_extra={"x-advanced": True})
    max_parallel: int = Field(
        default=2,
        ge=1,
        le=8,
        title="Services prepared at once",
        description="Independent services are prepared together, up to this many; changes to the monolith are always "
        "one service at a time.",
        json_schema_extra={"x-advanced": True},
    )
    use_llm: bool = Field(
        default=False,
        title="Use the model",
        description="Let the model name the groups (simulate: one real call at intake).",
    )

    @model_validator(mode="after")
    def _target_is_built(self) -> MicroservicesInputs:
        if self.simulate and self.target != "microservices":
            raise ValueError("Only the microservices conversion has simulated steps.")
        if self.mode == "conversion" and not self.simulate and self.target not in CONVERT_TARGETS:
            raise ValueError(
                "Pick a target to convert (clean modules, modular monolith, microservices, merge, serverless or "
                "event-driven); every target can be designed in audit mode."
            )
        return self


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
    # Phase 15: the real steps (design.py). The `*_brief` texts are what the approval cards show.
    intake_brief: NotRequired[str]
    as_is_brief: NotRequired[str]
    to_be_brief: NotRequired[str]
    language_brief: NotRequired[str]
    result_brief: NotRequired[str]
    report_brief: NotRequired[str]
    # Phase 16: the microservices conversion (microservices.py).
    foundation: NotRequired[dict[str, Any]]
    foundation_brief: NotRequired[str]
    ms_rules: NotRequired[dict[str, Any]]
    service_brief: NotRequired[str]
    db_split: NotRequired[dict[str, Any]]
    db_split_brief: NotRequired[str]
    frontend_brief: NotRequired[str]
    graph_before: NotRequired[dict[str, list[str]]]
    graph_change: NotRequired[str]
    outcomes: NotRequired[list[dict[str, Any]]]
    restructure_notes: NotRequired[list[str]]
    rules: NotRequired[dict[str, Any]]
    remaining_violations: NotRequired[list[dict[str, Any]]]
    diff: NotRequired[str]
    published: NotRequired[dict[str, Any]]
    done_summary: NotRequired[str]
    # Phase 17: per-target detail the generic `outcomes` can't hold (serverless's packages by name, event_driven's
    # subscriptions and unreviewed call sites), read back by `report()` and `comparison()`.
    platform_detail: NotRequired[dict[str, Any]]


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
        StepDef("restructure", "Restructure in small tested moves", "backend_developer"),
        StepDef("verify", "Prove behavior is unchanged", "qa_engineer"),
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
    lines = [f"# {STEPS[step].title} (stub)", "", "Written by the architecture-change playbook skeleton."]
    if feedback:
        lines += ["", f"Reworked after feedback: {feedback}"]
    (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
