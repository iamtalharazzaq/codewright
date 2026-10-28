"""Code review (CODEWRIGHT.md Section 5.1c), tier 0:

    scope → lint → review → report

- scope (Code Analyst): the target (file, folder, module or "payment") → files, code before tests, central modules
  first, capped at `max_files`.
- lint (QA Engineer): the language packs' linters in the sandbox, parsed to file:line findings; plus a secret scan.
- review (Tech Lead + Security Engineer): one structured call per file chunk, with the module's neighbours as context
  and the skill's rules when a skill runs this playbook.
- report (Technical Writer): merged findings by severity, a score out of 10 and the top 3; `review.md` and
  `findings.json` in the run folder, shown in the Report tab. Fixes come later (Phase 8), always after confirmation.
"""

from __future__ import annotations

import json
from typing import Any, NotRequired

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agent.llm.config import ProfileName
from agent.playbooks import steps
from agent.playbooks.llm_step import TaskResult, llm_step
from agent.playbooks.registry import PlaybookSpec, StepDef
from agent.playbooks.review_core import merge as merge_findings
from agent.playbooks.review_core import (
    parse_lint,
    rank,
    report_markdown,
    resolve_scope,
    review_files,
    secret_findings,
    summarize,
)
from agent.playbooks.services import RunServices
from agent.playbooks.state import RunState


class ReviewInputs(BaseModel):
    request: str = Field(default="", title="Request", max_length=4000)
    path: str = Field(
        default="", title="What to review", description="A file, folder or module; empty = the whole project."
    )
    max_files: int = Field(default=25, ge=1, le=200, title="Most files to review")
    run_linters: bool = Field(default=True, title="Run linters")
    security_pass: bool = Field(default=True, title="Security pass")
    use_llm: bool = Field(default=True, title="Use the model", json_schema_extra={"x-advanced": True})
    skill: dict[str, Any] | None = Field(default=None, json_schema_extra={"x-advanced": True})


class ReviewState(RunState):
    scope: NotRequired[dict[str, Any]]
    lint_findings: NotRequired[list[dict[str, Any]]]
    findings: NotRequired[list[dict[str, Any]]]
    review: NotRequired[dict[str, Any]]
    done_summary: NotRequired[str]


STEPS = (
    StepDef("scope", "Decide what to review", "code_analyst"),
    StepDef("lint", "Run the linters", "qa_engineer"),
    StepDef("review", "Review the code", "tech_lead"),
    StepDef("report", "Write the findings", "technical_writer"),
)


def scope_node(services: RunServices) -> Any:
    async def node(state: ReviewState) -> dict[str, Any]:
        plan = await steps.start(services, state, "scope", "code_analyst")
        project = services.project(str(state["project_id"]))
        graph = await project.fresh_graph()
        ids = [n["id"] for n in graph["nodes"]] if graph else []
        label, files = resolve_scope(project.work, state["inputs"].get("path", ""), ids)
        ordered = rank(files, project.work, graph)
        limit = int(state["inputs"].get("max_files", 25))
        chosen = ordered[:limit]
        scope = {"label": label, "files": chosen, "total": len(files), "skipped": max(0, len(files) - limit)}
        summary = f"{len(chosen)} of {len(files)} files in {label}"
        return await steps.finish(services, state, plan, "scope", "code_analyst", summary, scope=scope)

    return node


def lint_node(services: RunServices) -> Any:
    async def node(state: ReviewState) -> dict[str, Any]:
        plan = await steps.start(services, state, "lint", "qa_engineer")
        project = services.project(str(state["project_id"]))
        files = set(state["scope"]["files"])
        found: list[dict[str, Any]] = []
        notes: list[str] = []
        if state["inputs"].get("run_linters", True):
            try:
                outputs = await project.lint()
            except Exception as exc:  # the sandbox being down must not lose the review
                outputs, notes = [], [f"Linters didn't run: {exc}"]
            found = [f for f in parse_lint(outputs) if f["file"] in files]
            failed = [o for o in outputs if o.get("step") == "error"]
            notes += [f"Linters: {o['output'][:200]}" for o in failed]
        found += secret_findings(project.work, sorted(files))
        summary = f"{len(found)} findings from linters and the secret scan"
        update = {"lint_findings": found}
        if notes:
            update["errors"] = [{"step": "lint", "message": n} for n in notes]
        return await steps.finish(services, state, plan, "lint", "qa_engineer", summary, **update)

    return node


def review_node(services: RunServices) -> Any:
    async def node(state: ReviewState) -> dict[str, Any]:
        plan = await steps.start(services, state, "review", "tech_lead")
        project = services.project(str(state["project_id"]))
        files = state["scope"]["files"]
        if not state["inputs"].get("use_llm", True) or not files:
            return await steps.finish(services, state, plan, "review", "tech_lead", "Model review skipped", findings=[])
        graph = await project.fresh_graph()
        cache = steps.run_dir(state) / "cache"

        async def task(profile: ProfileName) -> TaskResult:
            client = services.llm(profile, run_id=state["run_id"], step="review", role="tech_lead")
            found, usage = await review_files(
                client,
                project.work,
                files,
                graph=graph,
                instructions=steps.skill_instructions(state),
                cache_dir=cache,
                security_pass=bool(state["inputs"].get("security_pass", True)),
            )
            return TaskResult({"findings": found}, usage.calls, usage.tokens)

        update = await llm_step(state, services, step="review", task=task)
        summary = f"{len(update['findings'])} findings from the review of {len(files)} files"
        return await steps.finish(services, state, plan, "review", "tech_lead", summary, **update)

    return node


def report_node(services: RunServices) -> Any:
    async def node(state: ReviewState) -> dict[str, Any]:
        plan = await steps.start(services, state, "report", "technical_writer")
        scope = state["scope"]
        findings = merge_findings([*state.get("lint_findings", []), *state.get("findings", [])])
        summary = summarize(findings, len(scope["files"]))
        notes = []
        if scope["skipped"]:
            notes.append(
                f"{scope['skipped']} more files were not reviewed (limit {len(scope['files'])}); "
                "review a module or folder to go deeper."
            )
        notes += [e["message"] for e in state.get("errors", []) if e["step"] == "lint"]
        skill = state["inputs"].get("skill")
        title = f"Code review: {skill['title']}" if skill else "Code review"
        md = report_markdown(title, scope["label"], findings, summary, notes)
        artifacts = [
            steps.write_artifact(state, "review.md", md, "report", "Code review", "report"),
            steps.write_artifact(
                state,
                "findings.json",
                json.dumps({"summary": summary, "findings": findings}, indent=1),
                "file",
                "Findings (JSON)",
                "report",
            ),
        ]
        c = summary["counts"]
        top = "\n".join(f"{i}. `{t['file']}:{t['line']}`: {t['problem']}" for i, t in enumerate(summary["top"], 1))
        done = (
            f"**Score {summary['score']}/10** · {c['critical']} critical · {c['major']} major · {c['minor']} minor · "
            f"{c['nit']} nit" + (f"\n\n**Fix these first:**\n{top}" if top else "")
        )
        line = f"Score {summary['score']}/10, {len(findings)} findings"
        return await steps.finish(
            services, state, plan, "report", "technical_writer", line,
            findings=findings, review=summary, artifacts=artifacts, done_summary=done,
        )  # fmt: skip

    return node


def build(services: RunServices) -> StateGraph[ReviewState, None, ReviewState, ReviewState]:
    g: StateGraph[ReviewState, None, ReviewState, ReviewState] = StateGraph(ReviewState)
    g.add_node("scope", scope_node(services))
    g.add_node("lint", lint_node(services))
    g.add_node("review", review_node(services))
    g.add_node("report", report_node(services))
    g.add_edge(START, "scope")
    g.add_edge("scope", "lint")
    g.add_edge("lint", "review")
    g.add_edge("review", "report")
    g.add_edge("report", END)
    return g


PLAYBOOK_SPEC = PlaybookSpec(
    inputs=ReviewInputs,
    steps=STEPS,
    gates=(),
    build=build,
    flow=lambda _inputs: [s.id for s in STEPS],
    initial_plan=lambda _inputs: [(s.id, s.title, s.role) for s in STEPS],
    needs_project=True,
)
