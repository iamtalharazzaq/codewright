"""Upgrade (CODEWRIGHT.md 5.11) end to end in the real sandbox runner (`make check-sandbox`; skipped otherwise):
survey (real `npm outdated`), plan (no model needed), the real bump + build + test, verify and publish all run
for real against a deliberately outdated dependency. One language (TypeScript) is enough to prove the pipeline
and the sandbox - every language's `upgrade_steps`/`outdated_steps` already has its own fake-mocked test, and
building a safe, stable "really outdated" fixture per registry (go module proxy, PyPI, npm) for all 5 is a lot
of fixture upkeep for the same proof. No model call happens at all here: the bumped dependency (lodash) isn't
used by any source file, so the build/tests stay green on the first try and the Reflection/adapt path never runs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tests.sandbox_harness import RealProject, start_session
from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import git

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(os.environ.get("SANDBOX_TESTS") != "1", reason="needs the sandbox runner: make check-sandbox"),
]
FIXTURES = Path(__file__).parent.parent / "fixtures" / "mini_apps" / "typescript"


class RealServices:
    """`RunServices` for this test: real events are dropped, the LLM is never actually called (no adaptation
    round is needed), every project id hands back the one real-sandbox workspace."""

    def __init__(self, project: RealProject, client: object) -> None:
        self._project = project
        self._client = client

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, object] | None = None
    ) -> None:
        return None

    def llm(self, profile: str, *, run_id: str, step: str, role: str) -> object:
        return self._client

    def chat_model(self, profile: str, *, run_id: str, step: str, role: str, **kwargs: object) -> object:
        raise NotImplementedError("this upgrade needs no adaptation round")

    def project(self, project_id: str) -> RealProject:
        return self._project

    async def create_project(self, run_id: str, name: str) -> str:
        raise AssertionError("upgrade should not need a new project in this test")


async def test_upgrade_bumps_an_outdated_dependency_and_keeps_tests_green(
    workspace: tuple[SandboxClient, str, Path],
) -> None:
    client, ws, work = workspace
    shutil.copytree(FIXTURES, work, dirs_exist_ok=True)
    pkg = json.loads((work / "package.json").read_text(encoding="utf-8"))
    pkg["dependencies"] = {"lodash": "4.17.20"}  # a real, long-stable package: unused by any source file
    (work / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")
    (work / "package-lock.json").unlink()  # out of sync with the added dependency; `npm install` regenerates it
    sid = await start_session(client, ws, work)
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(work)], check=True)  # noqa: S603, S607
    try:
        project = RealProject(client, sid, work)
        llm_client, _bodies = llm_returning()
        services = RealServices(project, llm_client)
        state = initial_state("upgrade", work, request="upgrade lodash")
        final, prompts = await drive(compiled("upgrade", services), cfg(), state, approve_all)  # type: ignore[arg-type]
        assert gates_of(prompts) == ["approve_plan", "approve_result"]
        assert [u["package"] for u in final["upgrades"]] == ["lodash"]
        assert [o["done"] for o in final["outcomes"]] == [True], final["outcomes"]
        assert final["verification"]["tests_ok"], final["verification"]
        branch = final["published"]["branch"]
        assert branch.startswith("codewright/upgrade-")
        assert git(work, "branch", "--show-current").strip() == branch
        log = git(work, "log", "--format=%s", branch, check=False)
        assert "lodash" in log
        pkg_after = json.loads((work / "package.json").read_text(encoding="utf-8"))
        assert pkg_after["dependencies"]["lodash"] != "4.17.20"
    finally:
        await client.delete_session(sid)
