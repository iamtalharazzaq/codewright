"""Frontend (CODEWRIGHT.md Section 5.14), tier 2 (approve the plan, approve the result):

    survey → plan → approve_plan ─approve→ migrate → modernize → verify → approve_result ─approve→ publish
                ↑        │ edit / reject      ↑                                │ edit / reject
                └────────┘                    └────────────────────────────────┘

- survey (Frontend Developer): the web frontends, a baseline (build, tests, screenshots of the pages) and a branch.
- plan (Frontend Developer): the stages the request asks for, shown for approval: `migrate` (React + Vite → Next.js)
  and/or `modernize` (design layer + accessibility fixes). No model is needed: both are computed from the source.
- migrate: the file operations of `migrate.py`, then build and tests. Red → every file goes back exactly as it was
  and the stage is reported as skipped. Green → its own commit, then screenshots compared with the baseline (parity).
- modernize: `a11y.py` fixes what source can prove, adds the design layer, builds and tests; red → undone.
  The screenshots then show before/after.
- verify (QA, UI/UX Designer): tests, build, the accessibility scan of the final source (what is fixed, what is left).
- publish: the commits are already on `codewright/frontend-<time>`.

Per the sandbox's design the screenshots come from Playwright in a browser container; when no page can be shown the
card says "not compared" instead of claiming parity.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace
from typing import Any, NotRequired

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agent.language_packs import detect_project
from agent.playbooks import steps
from agent.playbooks.code_edit import component_result, description, is_green, write_file
from agent.playbooks.frontend import a11y, migrate
from agent.playbooks.gates import after_gate, gate_node, plan_gate, result_gate
from agent.playbooks.registry import PlaybookSpec, StepDef
from agent.playbooks.services import ProjectTools, RunServices
from agent.playbooks.state import RunState
from agent.tools.workspace import git

WANTS_NEXT = re.compile(r"next\.?js|\bnext\b|migrat|move to|port to", re.I)
WANTS_MODERN = re.compile(r"modern|look|design|\bui\b|\bux\b|accessib|a11y|wcag|responsive|dark|style|polish", re.I)


class FrontendInputs(BaseModel):
    request: str = Field(default="", title="What to do", max_length=4000)
    path: str = Field(default="", title="Focus", description="Optional: the frontend's folder.")
    answers: list[Any] = Field(default_factory=list, json_schema_extra={"x-advanced": True})
    use_llm: bool = Field(default=True, title="Use the model", json_schema_extra={"x-advanced": True})
    skill: dict[str, Any] | None = Field(default=None, json_schema_extra={"x-advanced": True})


class FrontendState(RunState):
    branch: NotRequired[str]
    base: NotRequired[str]
    frontends: NotRequired[list[dict[str, Any]]]
    target: NotRequired[str]
    baseline: NotRequired[dict[str, Any]]
    stages: NotRequired[list[str]]
    plan_brief: NotRequired[str]
    outcomes: NotRequired[dict[str, Any]]
    verification: NotRequired[dict[str, Any]]
    result_brief: NotRequired[str]
    changed: NotRequired[list[str]]
    diff: NotRequired[str]
    published: NotRequired[dict[str, Any]]
    done_summary: NotRequired[str]


STEPS = (
    StepDef("survey", "Find the frontend and take a baseline", "frontend_developer"),
    StepDef("plan", "Plan the stages", "frontend_developer"),
    StepDef("migrate", "Move React + Vite to Next.js", "frontend_developer"),
    StepDef("modernize", "Modern, accessible UI", "ui_ux_designer"),
    StepDef("verify", "Check the tests, the build and accessibility", "qa_engineer"),
    StepDef("publish", "Keep the commits on the branch", "release_manager"),
)
PLAN_GATE = replace(plan_gate("plan"), summary_keys=("plan_brief",))
RESULT_GATE = result_gate(reworks="migrate", summary_keys=("result_brief",))


# ── helpers ──────────────────────────────────────────────────────────────────
async def build_and_test(project: ProjectTools, component: str) -> tuple[bool, str]:
    """Build and test one component. (green, why not)."""
    for r in await project.sandbox("build", [component]):
        if r.get("component", component) in (component, ".") and not r.get("ok"):
            return False, f"the build fails: {str(r.get('output', ''))[-300:].strip()}"
    result = component_result(await project.test([component]), component)
    if result is not None and not is_green(result.get("report")):
        return False, "the tests fail"
    return True, ""


def undo(work: Any, paths: list[str]) -> None:
    """Every path goes back exactly as committed; files that did not exist are removed."""
    for p in paths:
        if git(work, "ls-files", "--", p, check=False):
            git(work, "checkout", "HEAD", "--", p, check=False)
        else:
            remove_new(work, p)


def remove_new(work: Any, path: str) -> None:
    """Delete a file the run created, and the folders it leaves empty."""
    target = work / path
    target.unlink(missing_ok=True)
    for parent in target.parents:
        if parent == work or any(parent.iterdir()):
            break
        parent.rmdir()


def reset_to(work: Any, base: str) -> None:
    if base and git(work, "rev-parse", "HEAD", check=False) != base:
        git(work, "reset", "-q", "--hard", base, check=False)


async def screens(project: ProjectTools, component: str, *, accept: bool = False) -> dict[str, Any]:
    answer = await project.verify("screens", {"component": component, "accept": accept})
    report = answer.get("report") or {}
    summary = report.get("summary") or {}
    return {
        "ran": answer["ok"] is not None or bool(report),
        "ok": answer["ok"],
        "pages": summary.get("pages", 0),
        "changed": summary.get("changed", 0),
        "why": answer.get("error") or "",
        "id": report.get("id"),
    }


def commit(work: Any, paths: list[str], message: str) -> None:
    git(work, "add", "--", *paths, check=False)
    git(work, "commit", "-q", "-m", message, check=False)


# ── survey ───────────────────────────────────────────────────────────────────
def survey_node(services: RunServices) -> Any:
    async def node(state: FrontendState) -> dict[str, Any]:
        plan = await steps.start(services, state, "survey", "frontend_developer")
        project = services.project(str(state["project_id"]))
        focus = str(state["inputs"].get("path", "")).strip("/ ")
        found = [
            c
            for c in detect_project(project.work)
            if c.pack in {"typescript", "javascript"} and c.kind == "web" and focus in {"", c.path}
        ]
        frontends = [
            {"path": c.path, "pack": c.pack, "frameworks": c.frameworks, "migratable": migrate.can_migrate(c)}
            for c in found
        ]
        target = frontends[0]["path"] if frontends else ""
        git(project.work, "checkout", "-q", "-b", f"codewright/frontend-{time.strftime('%Y%m%d-%H%M%S')}", check=False)
        base = git(project.work, "rev-parse", "HEAD", check=False)
        baseline: dict[str, Any] = {}
        if target:
            green, why = await build_and_test(project, target)
            baseline = {"green": green, "why": why, "screens": await screens(project, target, accept=True)}
        return await steps.finish(
            services, state, plan, "survey", "frontend_developer",
            f"{len(frontends)} frontend(s)" + (f"; baseline {'green' if baseline.get('green') else 'not green'}" if target else ""),
            branch=git(project.work, "branch", "--show-current"), base=base, frontends=frontends, target=target, baseline=baseline,
        )  # fmt: skip

    return node


# ── plan ─────────────────────────────────────────────────────────────────────
def choose_stages(text: str, frontends: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    stages: list[str] = []
    migratable = bool(frontends and frontends[0]["migratable"])
    if WANTS_NEXT.search(text):
        if migratable:
            stages.append("migrate")
        else:
            notes.append(
                "A Next.js move was asked for, but this frontend is not a React + Vite app (or is already Next.js)."
            )
    if WANTS_MODERN.search(text) or not stages:
        stages.append("modernize")
    return stages, notes


def plan_node(services: RunServices) -> Any:
    async def node(state: FrontendState) -> dict[str, Any]:
        plan = await steps.start(services, state, "plan", "frontend_developer")
        project = services.project(str(state["project_id"]))
        text = description(state["inputs"]) + " " + state.get("feedback", {}).get("plan", "")
        frontends = state.get("frontends", [])
        if not frontends:
            brief = "No web frontend (React, Next.js, Vite) was found in this project, so there is nothing to do."
            return await steps.finish(
                services, state, plan, "plan", "frontend_developer", "no frontend", stages=[], plan_brief=brief
            )
        stages, notes = choose_stages(text, frontends)
        lines = [f"**Frontend:** `{state['target']}` ({', '.join(frontends[0]['frameworks']) or 'plain web'})", ""]
        if "migrate" in stages:
            m = migrate.migration(
                project.work, next(c for c in detect_project(project.work) if c.path == state["target"])
            )
            lines += ["**1. Move to Next.js** (App Router), the existing App unchanged under one route:"]
            lines += [f"- `{o.path}`: {o.why}" + (" (deleted)" if o.content is None else "") for o in m.operations[:14]]
            lines += [f"- …and {len(m.operations) - 14} more" for _ in [0] if len(m.operations) > 14]
            lines += [f"- {n}" for n in m.notes]
            if not m.supported:
                stages = [s for s in stages if s != "migrate"]
                notes += m.notes
        if "modernize" in stages:
            _, found = a11y.scan(project.work / state["target"], fix=True)
            by_rule: dict[str, int] = {}
            for f in found:
                by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
            lines += [
                f"**{len(stages)}. Modern, accessible UI:** adds `{a11y.TOKENS_FILE}` (colors with dark mode, focus rings, reduced motion, responsive defaults, all low-specificity so your styles win) and fixes automatically what the source proves.",  # noqa: E501
                "- Found now: "
                + (", ".join(f"{n}× {r}" for r, n in sorted(by_rule.items())) or "nothing the scan can see"),
            ]
        lines += [
            "",
            *[f"- {n}" for n in notes],
            "Each stage is built and tested and is undone if it cannot be made green. Screenshots before and after are compared.",  # noqa: E501
            "Not done: a redesign of layouts or components by a model. The design layer and the fixes are rule-based on purpose.",  # noqa: E501
        ]
        return await steps.finish(
            services, state, plan, "plan", "frontend_developer", " + ".join(stages) or "nothing to do",
            stages=stages, plan_brief="\n".join(lines),
        )  # fmt: skip

    return node


# ── migrate ──────────────────────────────────────────────────────────────────
def migrate_node(services: RunServices) -> Any:
    async def node(state: FrontendState) -> dict[str, Any]:
        plan = await steps.start(services, state, "migrate", "frontend_developer")
        project = services.project(str(state["project_id"]))
        work = project.work
        reset_to(work, state.get("base", ""))
        outcomes: dict[str, Any] = {}
        if "migrate" not in state.get("stages", []):
            return await steps.finish(
                services, state, plan, "migrate", "frontend_developer", "not planned", outcomes=outcomes
            )
        component = next(c for c in detect_project(work) if c.path == state["target"])
        m = migrate.migration(work, component)
        touched = [o.path for o in m.operations]
        for o in m.operations:
            if o.content is None:
                (work / o.path).unlink(missing_ok=True)
            else:
                write_file(work, o.path, o.content)
        green, why = await build_and_test(project, component.path)
        if not green:
            undo(work, touched)
            outcomes["migrate"] = {"done": False, "note": f"undone: {why}"}
            summary = "undone: " + why
        else:
            commit(work, touched, "Move the frontend from React + Vite to Next.js")
            project.files_changed(touched)
            shot = await screens(project, component.path)
            outcomes["migrate"] = {"done": True, "files": touched, "notes": m.notes, "parity": shot}
            await screens(project, component.path, accept=True)  # the modernize stage compares with the migrated app
            summary = "migrated; " + (
                f"{shot['changed']} of {shot['pages']} page(s) differ" if shot["ran"] else "pages not compared"
            )
        return await steps.finish(services, state, plan, "migrate", "frontend_developer", summary, outcomes=outcomes)

    return node


# ── modernize ────────────────────────────────────────────────────────────────
def entry_for_css(work: Any, target: str) -> tuple[str, str] | None:
    """(file, import line) that loads the design layer, whichever entry the frontend has now."""
    root = work / target
    for rel in ("src/app/layout.tsx", "app/layout.tsx", "src/app/layout.jsx", "app/layout.jsx"):
        if (root / rel).is_file():
            return rel, f"import '../{a11y.TOKENS_FILE}'"
    for rel in ("src/main.tsx", "src/main.jsx", "src/index.tsx", "src/index.jsx"):
        if (root / rel).is_file():
            return rel, f"import './{a11y.TOKENS_FILE}'"
    return None


def modernize_node(services: RunServices) -> Any:
    async def node(state: FrontendState) -> dict[str, Any]:
        plan = await steps.start(services, state, "modernize", "ui_ux_designer")
        project = services.project(str(state["project_id"]))
        work = project.work
        outcomes = dict(state.get("outcomes", {}))
        if "modernize" not in state.get("stages", []):
            return await steps.finish(
                services, state, plan, "modernize", "ui_ux_designer", "not planned", outcomes=outcomes
            )
        target = state["target"]
        root = work / target
        changed, found = a11y.scan(root, fix=True)
        entry = entry_for_css(work, target)
        prefix = "" if target == "." else f"{target}/"
        edits: dict[str, str] = {prefix + p: t for p, t in changed.items()}
        # the design layer sits in src/ (Vite) or the project folder (Next.js without src/); the entry imports it
        if entry:
            file, line = entry
            css_path = prefix + (f"src/{a11y.TOKENS_FILE}" if (root / "src").is_dir() else a11y.TOKENS_FILE)
            full_entry = prefix + file
            text = edits.get(full_entry) or (work / full_entry).read_text(encoding="utf-8")
            if a11y.TOKENS_FILE not in text:
                edits[full_entry] = _after_imports(text, line)
            edits[css_path] = a11y.tokens_css()
        touched = list(edits)
        before = {p: (work / p).read_text(encoding="utf-8") if (work / p).is_file() else None for p in touched}
        for p, t in edits.items():
            write_file(work, p, t)
        green, why = await build_and_test(project, target)
        if not green:
            for p, t in before.items():
                if t is None:
                    remove_new(work, p)
                else:
                    (work / p).write_text(t, encoding="utf-8")
            outcomes["modernize"] = {"done": False, "note": f"undone: {why}"}
            summary = "undone: " + why
        else:
            commit(work, touched, "Modern, accessible UI: design layer and accessibility fixes")
            project.files_changed(touched)
            shot = await screens(project, target)
            fixed = sum(f.fixed for f in found)
            outcomes["modernize"] = {
                "done": True,
                "files": touched,
                "fixed": fixed,
                "found": len(found),
                "screens": shot,
            }
            summary = f"{fixed} of {len(found)} accessibility finding(s) fixed"
        return await steps.finish(services, state, plan, "modernize", "ui_ux_designer", summary, outcomes=outcomes)

    return node


def _after_imports(text: str, line: str) -> str:
    """Put an import after the last import line of a module."""
    lines = text.splitlines()
    last = max((i for i, ln in enumerate(lines) if ln.startswith("import ")), default=-1)
    lines.insert(last + 1, line)
    return "\n".join(lines) + "\n"


# ── verify ───────────────────────────────────────────────────────────────────
def screens_line(label: str, s: dict[str, Any] | None) -> str:
    if not s or not s.get("ran"):
        return f"⚠️ **{label}:** not compared ({(s or {}).get('why') or 'no page could be shown'})."
    return f"{'✅' if not s['changed'] else 'ℹ️'} **{label}:** {s['changed']} of {s['pages']} page(s) look different. Open the Report tab for the screenshots."  # noqa: E501


def verify_node(services: RunServices) -> Any:
    async def node(state: FrontendState) -> dict[str, Any]:
        plan = await steps.start(services, state, "verify", "qa_engineer")
        project = services.project(str(state["project_id"]))
        target = state.get("target", "")
        outcomes = state.get("outcomes", {})
        kept = [k for k, v in outcomes.items() if v.get("done")]
        ok, why = (True, "")
        remaining: list[dict[str, Any]] = []
        if target and kept:
            ok, why = await build_and_test(project, target)
            _, found = a11y.scan(project.work / target, fix=False)
            remaining = [f.as_dict() for f in found]
        diff = git(project.work, "diff", state["base"], "HEAD", check=False) if kept else ""
        files = sorted({f for k in kept for f in outcomes[k].get("files", [])})
        lines = []
        for stage, title in (("migrate", "Next.js migration"), ("modernize", "Modern, accessible UI")):
            if stage in outcomes:
                o = outcomes[stage]
                lines.append(f"{'✅' if o['done'] else '⏭️'} **{title}**" + ("" if o["done"] else f": {o['note']}"))
        if "migrate" in outcomes and outcomes["migrate"].get("done"):
            lines.append(screens_line("Parity after the migration", outcomes["migrate"].get("parity")))
            lines += [f"- {n}" for n in outcomes["migrate"].get("notes", [])]
        if "modernize" in outcomes and outcomes["modernize"].get("done"):
            o = outcomes["modernize"]
            lines.append(screens_line("Before / after the new look", o.get("screens")))
            lines.append(
                f"{'✅' if not remaining else '⚠️'} **Accessibility (WCAG 2.2 AA, from source):** {o['fixed']} of {o['found']} finding(s) fixed automatically, {len(remaining)} left"
            )
            lines += [f"- `{f['file']}:{f['line']}` {f['message']} (WCAG {f['wcag']})" for f in remaining[:12]]
            if remaining:
                lines.append(
                    "These need a person: the code cannot know what a label or an icon means. Contrast set outside a rule that also sets the background is not visible to this scan."
                )
        lines += ["", f"{'✅' if ok else '❌'} **Final build and tests**" + ("" if ok else f": {why}")] if kept else []
        brief = "\n".join(lines) if lines else "Nothing was changed."
        artifacts = (
            [steps.write_artifact(state, "frontend.diff", diff, "diff", "The frontend changes", "verify")]
            if diff
            else []
        )
        return await steps.finish(
            services, state, plan, "verify", "qa_engineer", "green" if ok else "NOT green",
            verification={"ok": ok, "remaining": remaining}, changed=files, diff=diff, result_brief=brief, artifacts=artifacts,
        )  # fmt: skip

    return node


def publish_node(services: RunServices) -> Any:
    async def node(state: FrontendState) -> dict[str, Any]:
        plan = await steps.start(services, state, "publish", "release_manager")
        kept = [k for k, v in state.get("outcomes", {}).items() if v.get("done")]
        done = (
            f"Kept {len(kept)} stage(s) as separate commits on branch `{state['branch']}`. Deliver it from the project home."
            if kept
            else "Nothing was changed."
        )
        return await steps.finish(
            services, state, plan, "publish", "release_manager", done,
            published={"branch": state["branch"], "files": state.get("changed", [])},
            done_summary=state["result_brief"] + "\n\n" + done,
        )  # fmt: skip

    return node


def build(services: RunServices) -> StateGraph[FrontendState, None, FrontendState, FrontendState]:
    g: StateGraph[FrontendState, None, FrontendState, FrontendState] = StateGraph(FrontendState)
    g.add_node("survey", survey_node(services))
    g.add_node("plan", plan_node(services))
    g.add_node(PLAN_GATE.id, gate_node(PLAN_GATE))
    g.add_node("migrate", migrate_node(services))
    g.add_node("modernize", modernize_node(services))
    g.add_node("verify", verify_node(services))
    g.add_node(RESULT_GATE.id, gate_node(RESULT_GATE))
    g.add_node("publish", publish_node(services))
    g.add_edge(START, "survey")
    g.add_edge("survey", "plan")
    g.add_edge("plan", PLAN_GATE.id)
    g.add_conditional_edges(PLAN_GATE.id, after_gate(PLAN_GATE.id, "migrate", "plan"), ["migrate", "plan"])
    g.add_edge("migrate", "modernize")
    g.add_edge("modernize", "verify")
    g.add_edge("verify", RESULT_GATE.id)
    g.add_conditional_edges(RESULT_GATE.id, after_gate(RESULT_GATE.id, "publish", "migrate"), ["publish", "migrate"])
    g.add_edge("publish", END)
    return g


PLAYBOOK_SPEC = PlaybookSpec(
    inputs=FrontendInputs,
    steps=STEPS,
    gates=(PLAN_GATE, RESULT_GATE),
    build=build,
    flow=lambda _inputs: ["survey", "plan", PLAN_GATE.id, "migrate", "modernize", "verify", RESULT_GATE.id, "publish"],
    initial_plan=lambda _inputs: [(s.id, s.title, s.role) for s in STEPS],
    needs_project=True,
)
