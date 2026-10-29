"""Security review (CODEWRIGHT.md Section 5.8), tier 1 (review the scan) rising to tier 2 (approve a fix plan
first) when the request asks to fix something (`agent/chat/router.py`'s `_tier`):

    scan ─(nothing to fix)──────────────────────────────────┐
      │                                                      │
      └─(asked to fix)→ plan_gate ─approve→ fix → verify → result_gate ─approve→ publish → END
                  ↑ edit/reject                      ↑                  │ edit/reject
                  └──────────────────────────────────┘                  └──→ fix

- scan (Security Engineer): the Secret Scanner, the security-relevant part of the project's own linters, the
  Dependency Auditor (each Language Pack's `audit` step, Section 8.3), and the Security Engineer's own chunked
  review of every file in scope — merged into one findings report (secret/review_core's merge, sorted by severity).
  Asked to fix something, it also opens a branch, records the app's traffic, and proposes a plan for the worst
  findings (critical/major, at most four, each an existing file).
- fix (Backend Developer): `change_core.apply_steps` — the same whole-file-rewrite, test-after-each, undo-on-failure
  loop as Refactor and Performance.
- verify (QA Engineer): all tests, the recording replayed (identical behavior), and the scanners re-run on the
  changed files (clean, or a regression is reported honestly).
- publish: one commit on `codewright/security-<time>`.

A pure "review this" request never opens a branch or touches a file: it ends at the findings report, same as
Code review.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, NotRequired, cast

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agent.playbooks import steps
from agent.playbooks.change_core import (
    MAX_STEPS,
    ChangePlan,
    PlannedStep,
    apply_steps,
    baseline_recording,
    behavior_check,
    behavior_line,
    outcomes_markdown,
    plan_brief,
    scope_of,
)
from agent.playbooks.code_edit import component_result, description, is_green
from agent.playbooks.gates import after_gate, gate_node, needs_gate, plan_gate, result_gate
from agent.playbooks.llm_step import TaskResult, llm_step
from agent.playbooks.registry import PlaybookSpec, StepDef
from agent.playbooks.review_core import (
    Finding,
    parse_lint,
    rank,
    report_markdown,
    resolve_scope,
    review_file,
    secret_findings,
    summarize,
)
from agent.playbooks.review_core import merge as merge_findings
from agent.playbooks.security.scan import dependency_findings, dependency_note
from agent.playbooks.services import RunServices
from agent.playbooks.state import RunState
from agent.tools.workspace import git

MAX_SCOPE = 40  # files the cheap scans (secrets, lint) cover
MAX_LLM_FILES = 16  # files the Security Engineer's own chunked review covers (model cost)
MANIFESTS = {"package.json", "requirements.txt", "pyproject.toml", "setup.py", "go.mod"}


class SecurityReviewInputs(BaseModel):
    request: str = Field(default="", title="What to review (and fix, if anything)", max_length=4000)
    path: str = Field(default="", title="Focus", description="Optional: a file, folder or module.")
    answers: list[Any] = Field(default_factory=list, json_schema_extra={"x-advanced": True})
    use_llm: bool = Field(default=True, title="Use the model", json_schema_extra={"x-advanced": True})
    skill: dict[str, Any] | None = Field(default=None, json_schema_extra={"x-advanced": True})


class SecurityState(RunState):
    scope: NotRequired[list[str]]
    findings: NotRequired[list[dict[str, Any]]]
    report: NotRequired[str]
    fix_requested: NotRequired[bool]
    security_plan: NotRequired[dict[str, Any]]
    plan_brief: NotRequired[str]
    branch: NotRequired[str | None]
    recording: NotRequired[str | None]
    recording_note: NotRequired[str]
    originals: NotRequired[dict[str, str]]
    outcomes: NotRequired[list[dict[str, Any]]]
    verification: NotRequired[dict[str, Any] | None]
    rescan_note: NotRequired[str]
    changed: NotRequired[list[str]]
    result_brief: NotRequired[str]
    published: NotRequired[dict[str, Any]]
    done_summary: NotRequired[str]


STEPS = (
    StepDef("scan", "Scan for vulnerabilities", "security_engineer"),
    StepDef("plan", "Plan the fix", "security_engineer"),
    StepDef("fix", "Make the changes, testing after each", "backend_developer"),
    StepDef("verify", "Prove the fix and that behavior is unchanged", "qa_engineer"),
    StepDef("publish", "Add the fix to the project", "release_manager"),
)
PLAN_GATE = replace(plan_gate("scan"), summary_keys=("plan_brief",))
RESULT_GATE = result_gate(reworks="fix", summary_keys=("result_brief",))


# ── scan ─────────────────────────────────────────────────────────────────────
async def _dependency(project: Any) -> tuple[list[Finding], str]:
    outputs = await project.sandbox("audit", None)
    return dependency_findings(outputs, project.work), dependency_note(outputs)


async def _security_review(services: RunServices, state: SecurityState, files: list[str]) -> list[Finding]:
    project = services.project(str(state["project_id"]))

    async def task(profile: Any) -> TaskResult:
        client = services.llm(profile, run_id=state["run_id"], step="scan", role="security_engineer")
        found: list[Finding] = []
        for f in files[:MAX_LLM_FILES]:
            found += await review_file(client, project.work, f, role="security_engineer", note="A security review.")
        return TaskResult({"findings": found}, min(len(files), MAX_LLM_FILES), 0)

    update = await llm_step(state, services, step="scan", task=task)
    return cast(list[Finding], update["findings"])


def scan_node(services: RunServices) -> Any:
    async def node(state: SecurityState) -> dict[str, Any]:
        plan = await steps.start(services, state, "scan", "security_engineer")
        project = services.project(str(state["project_id"]))
        graph = await project.fresh_graph()
        ids = [n["id"] for n in graph["nodes"]] if graph else []
        label, files = resolve_scope(project.work, scope_of(project.work, state["inputs"], ids), ids)
        files = rank(files, project.work, graph)[:MAX_SCOPE]
        secrets = secret_findings(project.work, files)
        in_scope = set(files)
        static = [f for f in parse_lint(await project.lint()) if f["category"] == "security" and f["file"] in in_scope]
        dep, dep_note = await _dependency(project)
        llm_found = await _security_review(services, state, files) if state["inputs"].get("use_llm", True) else []
        merged = merge_findings([*secrets, *static, *dep, *llm_found])
        summary = summarize(merged, len(files))
        notes = [] if dep_note == "clean" else [f"Dependency audit: {dep_note}."]
        report = report_markdown("Security review", label or "the whole project", merged, summary, notes)

        fix_requested = state["tier"] >= 2
        change = ChangePlan(
            goal=description(state["inputs"]) or "Fix the critical and major security findings",
            risks="Behavior may change for code that relied on the vulnerability (e.g. a looser auth check).",
        )
        branch, recording, note = None, None, ""
        brief = ""
        if fix_requested:
            worst = [f for f in merged if f["severity"] in ("critical", "major")][:MAX_STEPS]
            change.steps = [
                PlannedStep(file=f["file"], change=f["problem"]) for f in worst if (project.work / f["file"]).is_file()
            ]
            git(
                project.work,
                "checkout",
                "-q",
                "-b",
                f"codewright/security-{time.strftime('%Y%m%d-%H%M%S')}",
                check=False,
            )
            branch = git(project.work, "branch", "--show-current").strip()
            recording, note = await baseline_recording(project)
            brief = plan_brief(change, note)
            if not change.steps:
                brief += "\n\nNo critical or major finding points at a file Codewright can rewrite."
        summary_line = f"{summary['total']} finding(s): {summary['counts']['critical']} critical, {summary['counts']['major']} major, {summary['counts']['minor']} minor, {summary['counts']['nit']} nit"  # noqa: E501
        return await steps.finish(
            services,
            state,
            plan,
            "scan",
            "security_engineer",
            summary_line,
            scope=files,
            findings=merged,
            report=report,
            fix_requested=fix_requested,
            security_plan=change.model_dump(),
            plan_brief=brief,
            branch=branch,
            recording=recording,
            recording_note=note,
            result_brief=""
            if fix_requested
            else "This was a review only; nothing was changed. See the findings report above.",
            artifacts=[steps.write_artifact(state, "security-report.md", report, "doc", "Security findings", "scan")],
        )

    return node


# ── fix ──────────────────────────────────────────────────────────────────────
def fix_node(services: RunServices) -> Any:
    async def node(state: SecurityState) -> dict[str, Any]:
        plan = await steps.start(services, state, "fix", "backend_developer")
        project = services.project(str(state["project_id"]))
        change = ChangePlan.model_validate(state["security_plan"])
        comment = state.get("feedback", {}).get("fix", "")
        totals = await apply_steps(
            services, state, project, change, step="fix", role="backend_developer", comment=comment
        )
        done = sum(o.done for o in totals.outcomes)
        usage = {"llm_calls": totals.llm_calls, "tokens": totals.tokens}
        return await steps.finish(
            services,
            state,
            plan,
            "fix",
            "backend_developer",
            f"{done} of {len(totals.outcomes)} fix(es) made",
            outcomes=[o.__dict__ for o in totals.outcomes],
            budget={"run": usage, "steps": {"fix": usage}, "extensions": 0},
        )

    return node


# ── verify ───────────────────────────────────────────────────────────────────
async def _rescan_clean(project: Any, changed: list[str]) -> tuple[bool, str]:
    """The same scanners, run only on the changed files (plus a fresh dependency audit if a manifest changed)."""
    secrets = secret_findings(project.work, changed)
    changed_set = set(changed)
    static = [f for f in parse_lint(await project.lint()) if f["category"] == "security" and f["file"] in changed_set]
    dep: list[Finding] = []
    if any(c.rsplit("/", 1)[-1] in MANIFESTS for c in changed):
        outputs = await project.sandbox("audit", None)
        dep = dependency_findings(outputs, project.work)
    found = [*secrets, *static, *dep]
    if not found:
        return True, "the scanners find nothing left on the changed files"
    return False, f"the scanners still find {len(found)} issue(s) on the changed files"


def verify_node(services: RunServices) -> Any:
    async def node(state: SecurityState) -> dict[str, Any]:
        plan = await steps.start(services, state, "verify", "qa_engineer")
        project = services.project(str(state["project_id"]))
        changed = [o["file"] for o in state.get("outcomes", []) if o["done"]]
        results = await project.test(None)
        tests_ok = bool(results) and all(
            is_green((component_result([r], r.get("component", ".")) or {}).get("report")) for r in results
        )
        passed = sum((r.get("report") or {}).get("passed", 0) for r in results)
        behavior: dict[str, Any] = {"checked": False, "why": "nothing was changed"}
        rescan_ok, rescan_note = True, "nothing was changed"
        if changed:
            project.files_changed(changed)
            behavior = await behavior_check(project, state.get("recording"))
            rescan_ok, rescan_note = await _rescan_clean(project, changed)
        verification = {"tests_ok": tests_ok, "tests_passed": passed, "behavior": behavior, "rescan_ok": rescan_ok}
        summary = f"tests {'pass' if tests_ok else 'FAIL'}; {rescan_note}"
        result_brief = _result_brief({**state, "verification": verification, "rescan_note": rescan_note})
        return await steps.finish(
            services,
            state,
            plan,
            "verify",
            "qa_engineer",
            summary,
            ok=tests_ok,
            verification=verification,
            rescan_note=rescan_note,
            result_brief=result_brief,
        )

    return node


# ── publish ──────────────────────────────────────────────────────────────────
def _result_brief(state: SecurityState) -> str:
    from agent.playbooks.change_core import StepOutcome  # noqa: PLC0415

    v = state.get("verification") or {}
    outcomes = [StepOutcome(**o) for o in state.get("outcomes", [])]
    lines = [
        outcomes_markdown(outcomes) or "No fix was made.",
        "",
        f"{'✅' if v.get('tests_ok') else '❌'} **Tests:** {v.get('tests_passed', 0)} passing"
        + ("" if v.get("tests_ok") else ", some failing"),
        behavior_line(v.get("behavior") or {}),
        ("✅" if v.get("rescan_ok") else "⚠️") + f" **Rescan:** {state.get('rescan_note', '')}",
    ]
    return "\n".join(lines)


def publish_node(services: RunServices) -> Any:
    async def node(state: SecurityState) -> dict[str, Any]:
        plan = await steps.start(services, state, "publish", "release_manager")
        project = services.project(str(state["project_id"]))
        changed = [o["file"] for o in state.get("outcomes", []) if o["done"]]
        if changed:
            git(project.work, "add", "-A", "--", *changed)
            git(
                project.work,
                "commit",
                "-q",
                "-m",
                f"Security fix: {(description(state['inputs']).splitlines() or ['by Codewright'])[0][:72]}",
                check=False,
            )
            project.files_changed(changed)
        done = (
            f"Fixed {len(changed)} finding(s) on branch `{state['branch']}`. Deliver it from the project home."
            if changed
            else "No fix was made; see the findings report above."
        )
        return await steps.finish(
            services,
            state,
            plan,
            "publish",
            "release_manager",
            done,
            changed=changed,
            published={"branch": state.get("branch"), "files": changed} if state.get("branch") else {},
            done_summary=state["report"] + "\n\n" + state["result_brief"] + "\n\n" + done,
        )

    return node


def build(services: RunServices) -> StateGraph[SecurityState, None, SecurityState, SecurityState]:
    g: StateGraph[SecurityState, None, SecurityState, SecurityState] = StateGraph(SecurityState)
    g.add_node("scan", scan_node(services))
    g.add_node(PLAN_GATE.id, gate_node(PLAN_GATE))
    g.add_node("fix", fix_node(services))
    g.add_node("verify", verify_node(services))
    g.add_node(RESULT_GATE.id, gate_node(RESULT_GATE))
    g.add_node("publish", publish_node(services))

    g.add_edge(START, "scan")
    g.add_conditional_edges(
        "scan",
        lambda s: (PLAN_GATE.id if needs_gate(s, "plan") else "fix") if s.get("fix_requested") else RESULT_GATE.id,
        [PLAN_GATE.id, "fix", RESULT_GATE.id],
    )
    g.add_conditional_edges(PLAN_GATE.id, after_gate(PLAN_GATE.id, "fix", "scan"), ["fix", "scan"])
    g.add_edge("fix", "verify")
    g.add_edge("verify", RESULT_GATE.id)
    g.add_conditional_edges(RESULT_GATE.id, after_gate(RESULT_GATE.id, "publish", "fix"), ["publish", "fix"])
    g.add_edge("publish", END)
    return g


PLAYBOOK_SPEC = PlaybookSpec(
    inputs=SecurityReviewInputs,
    steps=STEPS,
    gates=(PLAN_GATE, RESULT_GATE),
    build=build,
    flow=lambda _inputs: ["scan", PLAN_GATE.id, "fix", "verify", RESULT_GATE.id, "publish"],
    initial_plan=lambda _inputs: [(s.id, s.title, s.role) for s in STEPS],
    needs_project=True,
)
