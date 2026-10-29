"""New app (CODEWRIGHT.md 5.17, Phase 13): the `scaffold` and `verify` nodes against the real sandbox runner
(`make check-sandbox`; skipped otherwise). The real `cli-python` template is copied into a new project and committed
(`scaffold_node`), then the template's own tests and linters really run (`verify_node`). No model call happens in
either node; requirements, design and build (the model-driven parts) are not retrofitted, so their output
is hand-built state, the same way `test_new_app.py`'s fake-mocked tests build it.

The harness's `RealProject` needs a sandbox session, which needs the workspace to exist; `scaffold_node` creates the
workspace content itself, so the session starts between the two nodes. See PROGRESS.md's Retrofit section, Phase 13.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from agent.playbooks.new_app import graph as na
from agent.playbooks.new_app import stacks
from agent.tests.playbooks.helpers import initial_state
from agent.tests.sandbox_harness import RealProject, start_session
from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import git

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(os.environ.get("SANDBOX_TESTS") != "1", reason="needs the sandbox runner: make check-sandbox"),
]


class _Scaffolding:
    """What `scaffold_node` touches of a project before a sandbox session exists: the workspace path only."""

    def __init__(self, work: Path) -> None:
        self.work = work

    def files_changed(self, paths: list[str]) -> None:
        return None


class RealServices:
    """`RunServices` for these two nodes: events dropped, no model, one project handed out for the one workspace."""

    def __init__(self, work: Path) -> None:
        self._project: Any = _Scaffolding(work)
        self.created: list[str] = []

    def use(self, project: RealProject) -> None:
        self._project = project

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, object] | None = None
    ) -> None:
        return None

    def llm(self, profile: str, *, run_id: str, step: str, role: str) -> object:
        raise NotImplementedError("scaffold and verify need no model call")

    def chat_model(self, profile: str, *, run_id: str, step: str, role: str, **kwargs: object) -> object:
        raise NotImplementedError("scaffold and verify need no model call")

    def project(self, project_id: str) -> Any:
        return self._project

    async def create_project(self, run_id: str, name: str) -> str:
        self.created.append(name)
        return "p-new"


async def test_the_cli_python_template_is_scaffolded_committed_and_its_real_tests_pass(
    workspace: tuple[SandboxClient, str, Path],
) -> None:
    client, ws, work = workspace
    services = RealServices(work)
    state: dict[str, Any] = {
        **initial_state("new_app", work, request="A script that renames files", language="Python"),
        "project_id": None,  # the run manager gives a new app no project; the scaffold creates it
        "app_name": "renamer",
        "requirements": {"title": "File Renamer", "summary": "Renames files in a folder."},
        "choice": asdict(stacks.choose({"request": "A script that renames files", "language": "Python"})),
    }
    assert state["choice"]["template"] == "cli-python"

    state.update(await na.scaffold_node(services)(state))  # type: ignore[arg-type]
    assert services.created == ["File Renamer"] and state["project_id"] == "p-new"
    assert git(work, "log", "-1", "--format=%s") == "Start File Renamer from the cli-python template"
    assert git(work, "status", "--porcelain").strip() == ""

    sid = await start_session(client, ws, work)
    try:
        services.use(RealProject(client, sid, work))
        update = await na.verify_node(services)(state)  # type: ignore[arg-type]
        assert update["passed"] is True, update
        assert update["report"]["passed"] >= 1 and update["report"]["failed"] == 0
        assert not update["lint"]
    finally:
        await client.delete_session(sid)
