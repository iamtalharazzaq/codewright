"""Upgrade (CODEWRIGHT.md Section 5.11), tier 2 (approve the plan, approve the result):

    survey → plan → approve_plan ─approve→ upgrade → verify → approve_result ─approve→ publish
                ↑        │ edit / reject      ↑                       │ edit / reject
                └────────┘                    └───────────────────────┘

- survey (Code Analyst): each component's direct dependencies that its registry says are outdated (the pack's
  `outdated` step), the tests run once as a baseline, and the app's traffic recorded before anything changes.
  A branch is opened here.
- plan (Backend Developer): the packages the request names (to the version it names, else the latest), or with no
  package named the safest few (same major version). Shown for approval. No model is needed to plan.
- upgrade (Backend Developer): one package at a time, each its own commit: the pack's bump command, then build and
  tests; while they fail, the files the errors point at are adapted by the model (at most three rounds). An upgrade
  that is still red is reverted exactly and reported.
- verify (QA Engineer): all tests and the recording replayed against the upgraded app.
- publish: the commits are already on `codewright/upgrade-<time>`.

Release notes are not read: the sandbox cannot reach the web, and the brief says so.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace
from typing import Any, NotRequired

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agent.language_packs import detect_project, pack
from agent.playbooks import steps
from agent.playbooks.change_core import (
    ChangePlan,
    PlannedStep,
    apply_steps,
    baseline_recording,
    behavior_check,
    behavior_line,
)
from agent.playbooks.code_edit import component_result, description, is_green, result_failure
from agent.playbooks.gates import after_gate, gate_node, plan_gate, result_gate
from agent.playbooks.registry import PlaybookSpec, StepDef
from agent.playbooks.services import ProjectTools, RunServices
from agent.playbooks.state import RunState
from agent.playbooks.upgrade.outdated import Outdated, named_in, parse_outdated, version_in
from agent.tools.workspace import git

MAX_UPGRADES = 4
MAX_ROUNDS = 3  # build/test, then up to two rounds of adapting the code
MAX_ADAPT_FILES = 3
SOURCE = re.compile(r"([\w./-]+\.(?:go|py|ts|tsx|js|jsx|mjs|cpp|cc|h|hpp))")
SKIP_DIRS = ("node_modules/", "vendor/", ".venv/", "/site-packages/")
NO_NOTES = "Release notes were not read (the sandbox cannot reach the web); the compiler and the tests are the guide."


class UpgradeInputs(BaseModel):
    request: str = Field(default="", title="What to upgrade", max_length=4000)
    path: str = Field(default="", title="Focus", description="Optional: a folder or module.")
    answers: list[Any] = Field(default_factory=list, json_schema_extra={"x-advanced": True})
    use_llm: bool = Field(default=True, title="Use the model", json_schema_extra={"x-advanced": True})
    skill: dict[str, Any] | None = Field(default=None, json_schema_extra={"x-advanced": True})


class UpgradeState(RunState):
    branch: NotRequired[str]
    base: NotRequired[str]
    baseline_green: NotRequired[bool]
    recording: NotRequired[str | None]
    recording_note: NotRequired[str]
    candidates: NotRequired[list[dict[str, Any]]]
    survey_notes: NotRequired[list[str]]
    upgrades: NotRequired[list[dict[str, Any]]]
    plan_brief: NotRequired[str]
    outcomes: NotRequired[list[dict[str, Any]]]
    verification: NotRequired[dict[str, Any] | None]
    changed: NotRequired[list[str]]
    diff: NotRequired[str]
    result_brief: NotRequired[str]
    published: NotRequired[dict[str, Any]]
    done_summary: NotRequired[str]


STEPS = (
    StepDef("survey", "Find outdated dependencies and run the baseline", "code_analyst"),
    StepDef("plan", "Plan the upgrades", "backend_developer"),
    StepDef("upgrade", "Upgrade one package at a time, testing after each", "backend_developer"),
    StepDef("verify", "Prove the tests pass and behavior is unchanged", "qa_engineer"),
    StepDef("publish", "Keep the upgrades on the branch", "release_manager"),
)
PLAN_GATE = replace(plan_gate("plan"), summary_keys=("plan_brief",))
RESULT_GATE = result_gate(reworks="upgrade", summary_keys=("result_brief",))


# ── survey ───────────────────────────────────────────────────────────────────
async def find_outdated(project: ProjectTools) -> tuple[list[Outdated], list[str]]:
    found: list[Outdated] = []
    notes: list[str] = []
    for c in detect_project(project.work):
        p = pack(c.pack)
        listing = p.outdated_steps(project.work, c)
        if not listing:
            notes.append(f"{c.path} ({c.pack}): no registry to ask for newer versions")
            continue
        ready = True
        for step in [s for s in p.build_steps(project.work, c) if s.name == "install"]:
            if not (await project.run_step(step))["ok"]:
                notes.append(f"{c.path}: installing its dependencies failed, so nothing could be checked")
                ready = False
                break
        if ready:
            answer = await project.run_step(listing[0])
            found += parse_outdated(c.pack, c.path, answer["output"], project.work)
    return found, notes


def survey_node(services: RunServices) -> Any:
    async def node(state: UpgradeState) -> dict[str, Any]:
        plan = await steps.start(services, state, "survey", "code_analyst")
        project = services.project(str(state["project_id"]))
        outdated, notes = await find_outdated(project)
        git(project.work, "checkout", "-q", "-b", f"codewright/upgrade-{time.strftime('%Y%m%d-%H%M%S')}", check=False)
        base = git(project.work, "rev-parse", "HEAD", check=False)
        base_results = await project.test(None)
        green = bool(base_results) and all(is_green(r.get("report")) for r in base_results)
        recording, note = await baseline_recording(project)
        summary = f"{len(outdated)} outdated direct dependenc{'y' if len(outdated) == 1 else 'ies'}; tests {'pass' if green else 'do not all pass'} before"  # noqa: E501
        return await steps.finish(
            services,
            state,
            plan,
            "survey",
            "code_analyst",
            summary,
            branch=git(project.work, "branch", "--show-current"),
            base=base,
            baseline_green=green,
            recording=recording,
            recording_note=note,
            candidates=[o.__dict__ for o in outdated],
            survey_notes=notes,
        )

    return node


# ── plan ─────────────────────────────────────────────────────────────────────
def choose(text: str, candidates: list[Outdated]) -> list[dict[str, Any]]:
    named = named_in(text, candidates)
    asked = version_in(text)
    if named:
        chosen = named[:MAX_UPGRADES]
    else:
        wants_major = "major" in text.lower()
        chosen = [o for o in candidates if wants_major or o.same_major][:MAX_UPGRADES]
    out = []
    for o in chosen:
        target = o.latest
        if asked and len(named) == 1:
            target = f"v{asked}" if o.pack == "go" else asked
        out.append({"package": o.package, "current": o.current, "to": target, "component": o.component, "pack": o.pack})
    return out


def plan_node(services: RunServices) -> Any:
    async def node(state: UpgradeState) -> dict[str, Any]:
        plan = await steps.start(services, state, "plan", "backend_developer")
        text = description(state["inputs"]) + " " + state.get("feedback", {}).get("plan", "")
        candidates = [Outdated(**c) for c in state.get("candidates", [])]
        upgrades = choose(text, candidates)
        lines = [f"{i}. `{u['package']}` {u['current']} → {u['to']}" for i, u in enumerate(upgrades, 1)]
        if not upgrades:
            lines = [
                "Every direct dependency is up to date."
                if not candidates
                else "None of the outdated packages matches the request."
            ]
        brief = "\n".join(
            [
                *lines,
                "",
                "Each is bumped on its own, built and tested; one that cannot be made to pass is reverted.",
                NO_NOTES,
                *[f"- {n}" for n in state.get("survey_notes", [])],
                state.get("recording_note", ""),
            ]
        ).strip()
        return await steps.finish(
            services,
            state,
            plan,
            "plan",
            "backend_developer",
            f"{len(upgrades)} upgrade(s) planned",
            upgrades=upgrades,
            plan_brief=brief,
        )

    return node


# ── upgrade ──────────────────────────────────────────────────────────────────
def files_in(text: str, work: Any) -> list[str]:
    """The project's source files an error output names, as paths from the project root (a tool run inside a
    component, like `tsc` in `web/`, names them from there)."""
    prefixes = ["", *(f"{c.path}/" for c in detect_project(work) if c.path != ".")]
    out: list[str] = []
    for m in SOURCE.finditer(text):
        name = m.group(1).removeprefix("./")
        path = next((p + name for p in prefixes if (work / (p + name)).is_file()), None)
        if path and path not in out and not any(s in path for s in SKIP_DIRS):
            out.append(path)
    return out[:MAX_ADAPT_FILES]


def _dirty(work: Any) -> set[str]:
    return set(git(work, "diff", "--name-only", "HEAD", check=False).splitlines())


def reset_to(work: Any, base: str) -> None:
    """Undo every upgrade commit of this run (a rework starts again), leaving other files alone."""
    if not base or git(work, "rev-parse", "HEAD", check=False) == base:
        return
    files = git(work, "diff", "--name-only", base, "HEAD", check=False).splitlines()
    git(work, "reset", "-q", "--soft", base, check=False)
    if files:
        git(work, "checkout", base, "--", *files, check=False)


async def _green(project: ProjectTools, component: str) -> tuple[bool, str]:
    results = await project.test([component])
    result = component_result(results, component)
    return is_green((result or {}).get("report")), result_failure(result)


async def upgrade_one(
    services: RunServices, state: UpgradeState, project: ProjectTools, u: dict[str, Any]
) -> dict[str, Any]:
    work = project.work
    component = next((c for c in detect_project(work) if c.path == u["component"]), None)
    outcome = {"package": u["package"], "from": u["current"], "to": u["to"], "done": False, "rounds": 0, "note": ""}
    if component is None:
        return {**outcome, "note": "its component was not found"}
    before = _dirty(work)
    for step in pack(component.pack).upgrade_steps(work, component, u["package"], u["to"]):
        answer = await project.run_step(step)
        if not answer["ok"]:
            outcome["note"] = f"the bump failed: {answer['output'][-200:].strip()}"
            break
    else:
        failure = ""
        for rounds in range(1, MAX_ROUNDS + 1):
            outcome["rounds"] = rounds
            ok, failure = await _green(project, component.path)
            if ok:
                outcome["done"] = True
                break
            files = files_in(failure, work) if state["inputs"].get("use_llm", True) else []
            if rounds == MAX_ROUNDS or not files:
                outcome["note"] = f"still red after the upgrade: {failure[:160].strip()}"
                break
            change = ChangePlan(
                goal=f"Adapt the code to {u['package']} {u['to']}",
                steps=[
                    PlannedStep(file=f, change=f"Fix what upgrading {u['package']} to {u['to']} broke: {failure[:700]}")
                    for f in files
                ],
            )
            await apply_steps(services, state, project, change, step="upgrade", role="backend_developer", verify=False)
    changed = sorted(_dirty(work) - before)
    if outcome["done"]:
        git(work, "add", "--", *changed)
        git(work, "commit", "-q", "-m", f"Upgrade {u['package']} {u['current']} to {u['to']}", check=False)
        outcome["files"] = changed
    elif changed:
        git(work, "checkout", "HEAD", "--", *changed, check=False)  # exactly as it was
    return outcome


def upgrade_node(services: RunServices) -> Any:
    async def node(state: UpgradeState) -> dict[str, Any]:
        plan = await steps.start(services, state, "upgrade", "backend_developer")
        project = services.project(str(state["project_id"]))
        reset_to(project.work, state.get("base", ""))
        outcomes = [await upgrade_one(services, state, project, u) for u in state.get("upgrades", [])]
        done = sum(o["done"] for o in outcomes)
        return await steps.finish(
            services, state, plan, "upgrade", "backend_developer", f"{done} of {len(outcomes)} upgrade(s) made",
            outcomes=outcomes,
        )  # fmt: skip

    return node


# ── verify ───────────────────────────────────────────────────────────────────
def _brief(state: UpgradeState, diff: str) -> str:
    v = state.get("verification") or {}
    lines = []
    for o in state.get("outcomes", []):
        head = f"- {'✅' if o['done'] else '⏭️'} `{o['package']}` {o['from']} → {o['to']}"
        if o["done"]:
            lines.append(head + (f" (code adapted in round {o['rounds']})" if o["rounds"] > 1 else ""))
        else:
            lines.append(head + f": reverted, {o['note']}")
    lines += [
        "",
        f"{'✅' if v.get('tests_ok') else '❌'} **Tests:** {v.get('tests_passed', 0)} passing"
        + ("" if v.get("tests_ok") else ", some failing"),
        behavior_line(v.get("behavior") or {}),
        NO_NOTES,
        "",
        f"{len(diff.splitlines())} lines changed; open the Report tab to read the diff.",
    ]
    return "\n".join(lines) if state.get("outcomes") else "Nothing to upgrade.\n\n" + NO_NOTES


def verify_node(services: RunServices) -> Any:
    async def node(state: UpgradeState) -> dict[str, Any]:
        plan = await steps.start(services, state, "verify", "qa_engineer")
        project = services.project(str(state["project_id"]))
        done = [o for o in state.get("outcomes", []) if o["done"]]
        changed = sorted({f for o in done for f in o.get("files", [])})
        results = await project.test(None)
        tests_ok = bool(results) and all(
            is_green((component_result([r], r.get("component", ".")) or {}).get("report")) for r in results
        )
        passed = sum((r.get("report") or {}).get("passed", 0) for r in results)
        behavior: dict[str, Any] = {"checked": False, "why": "nothing was upgraded"}
        if done:
            project.files_changed(changed)
            behavior = await behavior_check(project, state.get("recording"))
        diff = git(project.work, "diff", state["base"], "HEAD", check=False) if done else ""
        verification = {"tests_ok": tests_ok, "tests_passed": passed, "behavior": behavior}
        brief = _brief({**state, "verification": verification}, diff)
        artifacts = (
            [steps.write_artifact(state, "upgrade.diff", diff, "diff", "The upgrades", "verify")] if diff else []
        )
        return await steps.finish(
            services, state, plan, "verify", "qa_engineer",
            f"tests {'pass' if tests_ok else 'FAIL'}; {len(done)} upgrade(s) kept",
            verification=verification, changed=changed, diff=diff, result_brief=brief, artifacts=artifacts,
        )  # fmt: skip

    return node


def publish_node(services: RunServices) -> Any:
    async def node(state: UpgradeState) -> dict[str, Any]:
        plan = await steps.start(services, state, "publish", "release_manager")
        kept = [o for o in state.get("outcomes", []) if o["done"]]
        done = (
            f"Kept {len(kept)} upgrade(s) as separate commits on branch `{state['branch']}`. Deliver it from the project home."  # noqa: E501
            if kept
            else "Nothing was upgraded."
        )
        return await steps.finish(
            services, state, plan, "publish", "release_manager", done,
            published={"branch": state["branch"], "files": state.get("changed", [])},
            done_summary=state["result_brief"] + "\n\n" + done,
        )  # fmt: skip

    return node


def build(services: RunServices) -> StateGraph[UpgradeState, None, UpgradeState, UpgradeState]:
    g: StateGraph[UpgradeState, None, UpgradeState, UpgradeState] = StateGraph(UpgradeState)
    g.add_node("survey", survey_node(services))
    g.add_node("plan", plan_node(services))
    g.add_node(PLAN_GATE.id, gate_node(PLAN_GATE))
    g.add_node("upgrade", upgrade_node(services))
    g.add_node("verify", verify_node(services))
    g.add_node(RESULT_GATE.id, gate_node(RESULT_GATE))
    g.add_node("publish", publish_node(services))
    g.add_edge(START, "survey")
    g.add_edge("survey", "plan")
    g.add_edge("plan", PLAN_GATE.id)
    g.add_conditional_edges(PLAN_GATE.id, after_gate(PLAN_GATE.id, "upgrade", "plan"), ["upgrade", "plan"])
    g.add_edge("upgrade", "verify")
    g.add_edge("verify", RESULT_GATE.id)
    g.add_conditional_edges(RESULT_GATE.id, after_gate(RESULT_GATE.id, "publish", "upgrade"), ["publish", "upgrade"])
    g.add_edge("publish", END)
    return g


PLAYBOOK_SPEC = PlaybookSpec(
    inputs=UpgradeInputs,
    steps=STEPS,
    gates=(PLAN_GATE, RESULT_GATE),
    build=build,
    flow=lambda _inputs: ["survey", "plan", PLAN_GATE.id, "upgrade", "verify", RESULT_GATE.id, "publish"],
    initial_plan=lambda _inputs: [(s.id, s.title, s.role) for s in STEPS],
    needs_project=True,
)
