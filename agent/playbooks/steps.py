"""Helpers every playbook node uses: step progress on the timeline and plan, and the run's own folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from agent.playbooks.plan import mark
from agent.playbooks.services import RunServices
from agent.playbooks.state import ArtifactRef, PlanItem, RunState


async def start(services: RunServices, state: RunState, step: str, role: str) -> list[PlanItem]:
    plan = mark(state.get("plan", []), step, "in_progress")
    await services.emit(state["run_id"], "step_started", step=step, data={"role": role})
    await services.emit(state["run_id"], "plan_updated", step=step, data={"plan": plan})
    return plan


async def finish(
    services: RunServices,
    state: RunState,
    plan: list[PlanItem],
    step: str,
    role: str,
    summary: str,
    *,
    ok: bool = True,
    **update: Any,
) -> dict[str, Any]:
    """Mark the step done (or, with `ok=False`, failed) and return the node's state update (plan, step result and
    `update`). `ok=False` is for a step whose own job was to verify something and that something did not pass
    (failing tests/lint, a build that stayed broken, etc.) — not for a step that merely reports findings."""
    status: Literal["done", "failed"] = "done" if ok else "failed"
    plan = mark(plan, step, status)
    await services.emit(state["run_id"], "plan_updated", step=step, data={"plan": plan})
    await services.emit(state["run_id"], "step_completed", step=step, data={"role": role, "summary": summary, "ok": ok})
    return {**update, "plan": plan, "steps": {step: {"status": status, "summary": summary}}}


def run_dir(state: RunState) -> Path:
    """`<workspace>/runs/<run id>`: reports, diagrams and caches of this run (artifact paths are relative to the
    workspace, so they read `runs/<id>/...`)."""
    folder = Path(state["workspace"]) / "runs" / state["run_id"]
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_artifact(state: RunState, name: str, text: str, kind: str, title: str, step: str) -> ArtifactRef:
    (run_dir(state) / name).write_text(text, encoding="utf-8")
    return {"kind": kind, "title": title, "path": f"runs/{state['run_id']}/{name}", "step": step}  # type: ignore[typeddict-item]


def skill_instructions(state: RunState) -> str:
    skill = state["inputs"].get("skill") or {}
    return str(skill.get("instructions") or "")
