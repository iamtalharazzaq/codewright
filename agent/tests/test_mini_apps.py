"""The shared mini-app fixtures (`agent/tests/fixtures/mini_apps/*`) actually build and pass their tests in the
real sandbox, in all 5 languages (`make check-sandbox`). This is the baseline every retrofit playbook test builds
on: if a fixture breaks here, every phase that reuses it breaks too, so it gets its own direct check.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from agent.language_packs import detect_project
from agent.language_packs.executor import run_action
from agent.tests.sandbox_harness import _events, start_session
from agent.tools.sandbox import SandboxClient

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(os.environ.get("SANDBOX_TESTS") != "1", reason="needs the sandbox runner: make check-sandbox"),
]
FIXTURES = Path(__file__).parent / "fixtures" / "mini_apps"
MIN_TESTS = {"python": 2, "typescript": 2, "javascript": 2, "go": 2, "cpp": 2}


@pytest.mark.parametrize("lang", sorted(MIN_TESTS))
async def test_mini_app_builds_and_tests(lang: str, workspace: tuple[SandboxClient, str, Path]) -> None:
    client, ws, work = workspace
    shutil.copytree(FIXTURES / lang, work, dirs_exist_ok=True)
    sid = await start_session(client, ws, work)
    try:
        [component] = detect_project(work)
        result = await run_action(client, sid, work, component, "test", _events)
        assert result.ok, [(s.step, s.output_tail) for s in result.steps if not s.ok]
        assert result.report and result.report.passed >= MIN_TESTS[lang], result.report
    finally:
        await client.delete_session(sid)
