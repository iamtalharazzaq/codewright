"""Code review (CODEWRIGHT.md 5.1c, Phase 6) end to end in the real sandbox runner (`make check-sandbox`; skipped
otherwise): scope, lint and report all run for real (lint runs the real `ruff` in the sandbox against the shared
`mini_apps/python` fixture's own known `avg()` off-by-one bug - the same bug `test_bug_fix_sandbox.py` fixes); only
the review step's one structured call is scripted, with a known-good finding on that same bug, since this proves the
pipeline and the real toolchain, not the model. Tier 0, no gates: the whole run is one `drive()` with no interrupts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.llm.client import LLMClient
from agent.tests.playbooks.helpers import cfg, compiled, drive, initial_state, llm_returning
from agent.tests.sandbox_harness import RealProject, start_session
from agent.tools.sandbox import SandboxClient

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(os.environ.get("SANDBOX_TESTS") != "1", reason="needs the sandbox runner: make check-sandbox"),
]
FIXTURE = Path(__file__).parent.parent / "fixtures" / "mini_apps" / "python"
SOURCE = "src/miniapp/core.py"

REVIEW_REPLY = {
    "findings": [
        {
            "line": 23,
            "evidence": "len(nums) + 1",
            "problem": "avg divides by len(nums) + 1, one more than the real count, so the result is always too "
            "small for any non-empty list.",
            "why": "Callers get a wrong average silently, with no error to catch it.",
            "category": "bug",
            "severity": "major",
            "fix": "return sum(nums) / len(nums)",
        }
    ]
}


class RealServices:
    """`RunServices` for this test: real events are dropped, the LLM is scripted (one structured call: the review
    step), every project id hands back the one real-sandbox workspace."""

    def __init__(self, project: RealProject, client: LLMClient) -> None:
        self._project = project
        self._client = client

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, object] | None = None
    ) -> None:
        return None

    def llm(self, profile: str, *, run_id: str, step: str, role: str) -> LLMClient:
        return self._client

    def project(self, project_id: str) -> RealProject:
        return self._project

    async def create_project(self, run_id: str, name: str) -> str:
        raise AssertionError("code_review should not need a new project in this test")


async def test_a_review_finds_the_shared_avg_bug_and_writes_the_report(
    workspace: tuple[SandboxClient, str, Path],
) -> None:
    client, ws, work = workspace
    shutil.copytree(FIXTURE, work, dirs_exist_ok=True)
    sid = await start_session(client, ws, work)
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(work)], check=True)  # noqa: S603, S607
    try:
        project = RealProject(client, sid, work)
        llm_client, _bodies = llm_returning(json.dumps(REVIEW_REPLY))
        services = RealServices(project, llm_client)
        state = initial_state("code_review", work, path=SOURCE)

        final, prompts = await drive(compiled("code_review", services), cfg(), state, lambda p: None)  # type: ignore[arg-type]
        assert prompts == []  # tier 0, no gates: the run finishes without a single interrupt

        assert final["scope"]["files"] == [SOURCE]
        findings = final["findings"]
        assert any(f["file"] == SOURCE and f["line"] == 23 and f["category"] == "bug" for f in findings), findings
        assert final["review"]["score"] < 10, final["review"]
        report = (work / "runs" / final["run_id"] / "review.md").read_text(encoding="utf-8")
        assert "avg" in report
        found = json.loads((work / "runs" / final["run_id"] / "findings.json").read_text(encoding="utf-8"))
        assert any(f["line"] == 23 for f in found["findings"]), found
    finally:
        await client.delete_session(sid)
