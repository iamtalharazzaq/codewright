"""Add a feature (CODEWRIGHT.md Section 5.13) end to end in the real sandbox runner (`make check-sandbox`; skipped
otherwise): survey (real search + real tests as a baseline), design (no analog exists in this tiny fixture, so the
model is asked for a plain file plan), build (the Reflection loop actually writes and tests the new files for real),
verify and publish all run for real. Python only: feature's build step is a bigger lift to script per language than
write_code/bug_fix/tests were (new files in each language's own test convention), and this already proves the whole
pipeline and the real toolchain, not the model.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.llm.client import LLMClient
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tests.sandbox_harness import RealProject, start_session
from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import git

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(os.environ.get("SANDBOX_TESTS") != "1", reason="needs the sandbox runner: make check-sandbox"),
]
FIXTURES = Path(__file__).parent.parent / "fixtures" / "mini_apps" / "python"

STORIES = {
    "title": "Shout",
    "stories": ["As a user, I want a shout function so that I can emphasize text."],
    "criteria": ["Shouting text upper-cases it and adds an exclamation mark"],
}
PLAN = {
    "goal": "Add a shout(text) helper",
    "steps": [
        {"file": "src/miniapp/shout.py", "change": "Upper-case text and add an exclamation mark", "new": True},
        {
            "file": "src/miniapp/test_shout_codewright.py",
            "change": "Test that shout upper-cases and adds '!'",
            "new": True,
        },
    ],
    "screens": [],
    "risks": "none",
}
SHOUT = "def shout(text: str) -> str:\n    return text.upper() + '!'\n"
TEST_SHOUT = "from miniapp.shout import shout\n\n\ndef test_shout():\n    assert shout('hi') == 'HI!'\n"


def fenced(text: str) -> str:
    return f"```\n{text}\n```"


class RealServices:
    """`RunServices` for this test: real events are dropped, the LLM is scripted, every project id hands back the
    one real-sandbox workspace."""

    def __init__(self, project: RealProject, client: LLMClient) -> None:
        self._project = project
        self._client = client

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, object] | None = None
    ) -> None:
        return None

    def llm(self, profile: str, *, run_id: str, step: str, role: str) -> LLMClient:
        return self._client

    def chat_model(self, profile: str, *, run_id: str, step: str, role: str, **kwargs: object) -> object:
        raise NotImplementedError("feature's build step uses apply_steps, not an agent loop")

    def project(self, project_id: str) -> RealProject:
        return self._project

    async def create_project(self, run_id: str, name: str) -> str:
        raise AssertionError("feature should not need a new project in this test")


async def test_a_feature_is_designed_built_tested_and_committed(workspace: tuple[SandboxClient, str, Path]) -> None:
    client, ws, work = workspace
    shutil.copytree(FIXTURES, work, dirs_exist_ok=True)
    sid = await start_session(client, ws, work)
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(work)], check=True)  # noqa: S603, S607
    try:
        project = RealProject(client, sid, work)
        llm_client, _bodies = llm_returning(STORIES, PLAN, fenced(SHOUT), fenced(TEST_SHOUT))
        services = RealServices(project, llm_client)
        state = initial_state("feature", work, request="add a shout function")
        final, prompts = await drive(compiled("feature", services), cfg(), state, approve_all)  # type: ignore[arg-type]
        assert gates_of(prompts) == ["approve_plan", "approve_result"]
        assert final["built"] is True
        assert sorted(final["changed"]) == ["src/miniapp/shout.py", "src/miniapp/test_shout_codewright.py"]
        assert "shout" in (work / "src/miniapp/shout.py").read_text(encoding="utf-8")
        assert final["verification"]["tests_ok"], final["verification"]
        branch = final["published"]["branch"]
        assert branch.startswith("codewright/feature-")
        assert git(work, "branch", "--show-current").strip() == branch
        assert git(work, "log", "-1", "--format=%s") == "Add feature: Shout"
    finally:
        await client.delete_session(sid)
