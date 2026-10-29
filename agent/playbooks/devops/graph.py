"""DevOps (CODEWRIGHT.md Section 5.15), tier 2 (approve the plan, approve the result):

    survey → plan → approve_plan ─approve→ generate → verify → approve_result ─approve→ publish
                ↑        │ edit / reject      ↑                       │ edit / reject
                └────────┘                    └───────────────────────┘

- survey (DevOps Engineer): the deployable components, their ports and health routes, the databases the dependency
  manifests mention. A branch is opened here.
- plan (DevOps Engineer): the files to add (Dockerfile + .dockerignore per component, Compose, CI, Kubernetes when the
  request asks), and what is left alone because it exists. No model is needed: the files come from templates per pack.
- generate (DevOps Engineer): writes the files and commits them.
- verify (Security Engineer, QA Engineer): static checks on the files (pinned images, non-root user, COPY sources
  exist, valid YAML, no secrets, no Docker socket), then the CI's own commands run in the sandbox (build, tests).
  Building the images is not run: the sandbox has no Docker daemon, by design.
- publish: the commit is already on `codewright/devops-<time>`.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, NotRequired

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agent.playbooks import steps
from agent.playbooks.code_edit import description, is_green, write_file
from agent.playbooks.devops import files as gen
from agent.playbooks.gates import after_gate, gate_node, plan_gate, result_gate
from agent.playbooks.registry import PlaybookSpec, StepDef
from agent.playbooks.services import RunServices
from agent.playbooks.state import RunState
from agent.tools.workspace import git

NOT_BUILT = (
    "The images were **not built**: the sandbox has no Docker daemon, by design. The files are checked statically "
    "and the CI's commands run, but run `docker compose build` once on a machine with Docker."
)


class DevOpsInputs(BaseModel):
    request: str = Field(default="", title="What to set up", max_length=4000)
    path: str = Field(default="", title="Focus", description="Optional: a folder or module.")
    answers: list[Any] = Field(default_factory=list, json_schema_extra={"x-advanced": True})
    use_llm: bool = Field(default=True, title="Use the model", json_schema_extra={"x-advanced": True})
    skill: dict[str, Any] | None = Field(default=None, json_schema_extra={"x-advanced": True})


class DevOpsState(RunState):
    branch: NotRequired[str]
    base: NotRequired[str]
    components: NotRequired[list[dict[str, Any]]]
    files: NotRequired[list[dict[str, str]]]
    notes: NotRequired[list[str]]
    plan_brief: NotRequired[str]
    written: NotRequired[list[str]]
    findings: NotRequired[list[dict[str, str]]]
    ci: NotRequired[list[dict[str, Any]]]
    result_brief: NotRequired[str]
    diff: NotRequired[str]
    published: NotRequired[dict[str, Any]]
    done_summary: NotRequired[str]


STEPS = (
    StepDef("survey", "Find what can be deployed", "devops_engineer"),
    StepDef("plan", "Plan the files", "devops_engineer"),
    StepDef("generate", "Write the files", "devops_engineer"),
    StepDef("verify", "Check the files and run the CI commands", "security_engineer"),
    StepDef("publish", "Keep the files on the branch", "release_manager"),
)
PLAN_GATE = replace(plan_gate("plan"), summary_keys=("plan_brief",))
RESULT_GATE = result_gate(reworks="generate", summary_keys=("result_brief",))


def survey_node(services: RunServices) -> Any:
    async def node(state: DevOpsState) -> dict[str, Any]:
        plan = await steps.start(services, state, "survey", "devops_engineer")
        project = services.project(str(state["project_id"]))
        found = gen.targets(project.work)
        git(project.work, "checkout", "-q", "-b", f"codewright/devops-{time.strftime('%Y%m%d-%H%M%S')}", check=False)
        base = git(project.work, "rev-parse", "HEAD", check=False)
        components = [
            {
                "name": t.name,
                "path": t.component.path,
                "pack": t.component.pack,
                "kind": t.component.kind,
                "port": gen.serving_port(t),
                "health": t.health,
            }
            for t in found
        ]
        return await steps.finish(
            services, state, plan, "survey", "devops_engineer",
            f"{len(components)} deployable component(s)",
            branch=git(project.work, "branch", "--show-current"), base=base, components=components,
        )  # fmt: skip

    return node


def plan_node(services: RunServices) -> Any:
    async def node(state: DevOpsState) -> dict[str, Any]:
        plan = await steps.start(services, state, "plan", "devops_engineer")
        project = services.project(str(state["project_id"]))
        text = description(state["inputs"]) + " " + state.get("feedback", {}).get("plan", "")
        files, notes = gen.plan_files(project.work, text)
        lines = [f"{i}. `{f.path}`: {f.purpose}" for i, f in enumerate(files, 1)] or ["Nothing to add."]
        comps = [
            f"- `{c['name']}` ({c['pack']} {c['kind']}) on port {c['port']}"
            + (f", health route `{c['health']}`" if c["health"] else ", no health route found: a TCP probe is used")
            for c in state.get("components", [])
        ]
        brief = "\n".join(
            [
                *(["**Deployable parts:**", *comps, ""] if comps else []),
                "**Files to add:**",
                *lines,
                "",
                *[f"- {n}" for n in notes],
                "Files come from templates for each language, not from a model, and existing files are never overwritten.",  # noqa: E501
                NOT_BUILT,
            ]
        )
        return await steps.finish(
            services, state, plan, "plan", "devops_engineer", f"{len(files)} file(s) planned",
            files=[{"path": f.path, "content": f.content, "purpose": f.purpose} for f in files],
            notes=notes, plan_brief=brief,
        )  # fmt: skip

    return node


def reset_to(work: Any, base: str) -> None:
    """A rework starts again: drop this run's commit and files."""
    if not base or git(work, "rev-parse", "HEAD", check=False) == base:
        return
    git(work, "reset", "-q", "--hard", base, check=False)


def generate_node(services: RunServices) -> Any:
    async def node(state: DevOpsState) -> dict[str, Any]:
        plan = await steps.start(services, state, "generate", "devops_engineer")
        project = services.project(str(state["project_id"]))
        reset_to(project.work, state.get("base", ""))
        written: list[str] = []
        for f in state.get("files", []):
            if not (project.work / f["path"]).exists():
                write_file(project.work, f["path"], f["content"])
                written.append(f["path"])
        if written:
            git(project.work, "add", "--", *written)
            git(project.work, "commit", "-q", "-m", "Add Docker, CI and deployment files", check=False)
            project.files_changed(written)
        return await steps.finish(
            services, state, plan, "generate", "devops_engineer", f"{len(written)} file(s) written", written=written
        )

    return node


async def run_ci(project: Any) -> list[dict[str, Any]]:
    """The CI's commands in the sandbox: build every component, then its tests, lint only reported."""
    results: list[dict[str, Any]] = []
    for r in await project.sandbox("build"):
        results.append({"what": f"build {r.get('component', '.')}", "ok": bool(r.get("ok")), "note": ""})
    for r in await project.test(None):
        report = r.get("report")
        results.append(
            {
                "what": f"test {r.get('component', '.')}",
                "ok": is_green(report),
                "note": f"{(report or {}).get('passed', 0)} passing",
            }
        )
    return results


def brief_of(state: DevOpsState, diff: str) -> str:
    findings = state.get("findings", [])
    ci = state.get("ci", [])
    lines = [f"**Added** {len(state.get('written', []))} file(s) on branch `{state.get('branch')}`:"]
    lines += [f"- `{p}`" for p in state.get("written", [])]
    lines += [""]
    if findings:
        lines += [
            "❌ **Security checks on the files:**",
            *[f"- {f['severity']}: `{f['file']}` {f['problem']}" for f in findings],
        ]
    else:
        lines += [
            "✅ **Security checks on the files:** pinned images, no root user, no secrets, no Docker socket, every COPY source exists, valid YAML."  # noqa: E501
        ]
    for c in ci:
        lines.append(f"{'✅' if c['ok'] else '❌'} **CI step** {c['what']}" + (f" ({c['note']})" if c["note"] else ""))
    lines += [
        "",
        NOT_BUILT,
        *[f"- {n}" for n in state.get("notes", [])],
        "",
        f"{len(diff.splitlines())} lines added; open the Report tab to read them.",
    ]
    return "\n".join(lines)


def verify_node(services: RunServices) -> Any:
    async def node(state: DevOpsState) -> dict[str, Any]:
        plan = await steps.start(services, state, "verify", "security_engineer")
        project = services.project(str(state["project_id"]))
        written = state.get("written", [])
        by_path = {f["path"]: gen.GeneratedFile(f["path"], f["content"], f["purpose"]) for f in state.get("files", [])}
        findings = gen.check_files(project.work, [by_path[p] for p in written if p in by_path])
        ci = await run_ci(project) if written else []
        diff = git(project.work, "diff", state["base"], "HEAD", check=False) if written else ""
        brief = brief_of({**state, "findings": findings, "ci": ci}, diff)
        artifacts = (
            [steps.write_artifact(state, "devops.diff", diff, "diff", "The deployment files", "verify")] if diff else []
        )
        bad = len(findings) + sum(not c["ok"] for c in ci)
        return await steps.finish(
            services, state, plan, "verify", "security_engineer",
            "all checks pass" if not bad else f"{bad} problem(s) found",
            ok=not bad,
            findings=findings, ci=ci, diff=diff, result_brief=brief, artifacts=artifacts,
        )  # fmt: skip

    return node


def publish_node(services: RunServices) -> Any:
    async def node(state: DevOpsState) -> dict[str, Any]:
        plan = await steps.start(services, state, "publish", "release_manager")
        written = state.get("written", [])
        done = (
            f"Kept {len(written)} file(s) as one commit on branch `{state['branch']}`. Deliver it from the project home."  # noqa: E501
            if written
            else "Nothing was added."
        )
        return await steps.finish(
            services, state, plan, "publish", "release_manager", done,
            published={"branch": state["branch"], "files": written},
            done_summary=state["result_brief"] + "\n\n" + done,
        )  # fmt: skip

    return node


def build(services: RunServices) -> StateGraph[DevOpsState, None, DevOpsState, DevOpsState]:
    g: StateGraph[DevOpsState, None, DevOpsState, DevOpsState] = StateGraph(DevOpsState)
    g.add_node("survey", survey_node(services))
    g.add_node("plan", plan_node(services))
    g.add_node(PLAN_GATE.id, gate_node(PLAN_GATE))
    g.add_node("generate", generate_node(services))
    g.add_node("verify", verify_node(services))
    g.add_node(RESULT_GATE.id, gate_node(RESULT_GATE))
    g.add_node("publish", publish_node(services))
    g.add_edge(START, "survey")
    g.add_edge("survey", "plan")
    g.add_edge("plan", PLAN_GATE.id)
    g.add_conditional_edges(PLAN_GATE.id, after_gate(PLAN_GATE.id, "generate", "plan"), ["generate", "plan"])
    g.add_edge("generate", "verify")
    g.add_edge("verify", RESULT_GATE.id)
    g.add_conditional_edges(RESULT_GATE.id, after_gate(RESULT_GATE.id, "publish", "generate"), ["publish", "generate"])
    g.add_edge("publish", END)
    return g


PLAYBOOK_SPEC = PlaybookSpec(
    inputs=DevOpsInputs,
    steps=STEPS,
    gates=(PLAN_GATE, RESULT_GATE),
    build=build,
    flow=lambda _inputs: ["survey", "plan", PLAN_GATE.id, "generate", "verify", RESULT_GATE.id, "publish"],
    initial_plan=lambda _inputs: [(s.id, s.title, s.role) for s in STEPS],
    needs_project=True,
)
