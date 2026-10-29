"""Performance (CODEWRIGHT.md 5.10) end to end in the real sandbox runner (`make check-sandbox`; skipped
otherwise), for every language: baseline, find (real code search), the Reflection-loop rewrite, verify (real
tests; bench/replay honestly "not measured" since these fixtures have no runnable app), review and publish all
run for real. Reuses `test_refactor_sandbox`'s fixtures and scripted fix (a trivial, behavior-preserving change
is enough to prove the pipeline; the model is scripted either way).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tests.playbooks.test_refactor_sandbox import CASES, RealServices, fenced, plan_for
from agent.tests.sandbox_harness import RealProject, start_session
from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import git

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(os.environ.get("SANDBOX_TESTS") != "1", reason="needs the sandbox runner: make check-sandbox"),
]
FIXTURES = Path(__file__).parent.parent / "fixtures" / "mini_apps"


@pytest.mark.parametrize("lang", sorted(CASES))
async def test_performance_finds_and_fixes_via_real_search_not_measured_bench(
    lang: str, workspace: tuple[SandboxClient, str, Path]
) -> None:
    client, ws, work = workspace
    case = CASES[lang]
    shutil.copytree(FIXTURES / case["fixture"], work, dirs_exist_ok=True)
    sid = await start_session(client, ws, work)
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(work)], check=True)  # noqa: S603, S607
    try:
        project = RealProject(client, sid, work)
        llm_client, _bodies = llm_returning(plan_for(case["source"]), fenced(case["fixed"]), '{"findings": []}')
        services = RealServices(project, llm_client)
        # Words that literally appear in greet()'s source, in every language, so the real `search()` finds the
        # file without depending on the static smell-scan (these fixtures have no DB/sleep code to smell).
        state = initial_state("performance", work, request="make greet faster: hello world", path=case["source"])
        final, prompts = await drive(compiled("performance", services), cfg(), state, approve_all)  # type: ignore[arg-type]
        assert gates_of(prompts) == ["approve_plan", "approve_result"]
        assert case["source"] in final["candidates"], final["candidates"]
        assert [o["done"] for o in final["outcomes"]] == [True], final["outcomes"]
        assert final["verification"]["tests_ok"], final["verification"]
        assert "not measured" in final["result_brief"].lower()
        branch = final["published"]["branch"]
        assert branch.startswith("codewright/perf-")
        assert git(work, "branch", "--show-current").strip() == branch
        assert case["source"] in git(work, "show", "--stat", "--format=", "HEAD")
    finally:
        await client.delete_session(sid)
