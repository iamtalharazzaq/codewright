"""Tests (CODEWRIGHT.md 5.6) end to end in the real sandbox runner (`make check-sandbox`; skipped otherwise), for
every language: picking a target, writing a characterization test (Reflection loop), before/after and publish all
run for real against the shared mini-app fixtures. Only the model is scripted (a known-good new test per
language), since this proves the pipeline and the sandbox, not the model.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.llm.client import LLMClient
from agent.playbooks.code_edit import own_test_file
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tests.sandbox_harness import RealProject, start_session
from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import git

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(os.environ.get("SANDBOX_TESTS") != "1", reason="needs the sandbox runner: make check-sandbox"),
]
FIXTURES = Path(__file__).parent.parent / "fixtures" / "mini_apps"

# Per language: a request naming the exact source file (so `targets` finds it without depending on search
# ranking) and a new characterization test for word_count's untested empty-string case.
CASES: dict[str, dict[str, str]] = {
    "python": {
        "fixture": "python",
        "pack": "python",
        "source": "src/miniapp/core.py",
        "request": "Add tests for word_count in src/miniapp/core.py, including the empty string case.",
        "test": "from miniapp.core import word_count\n\n\n"
        'def test_word_count_empty_string_codewright() -> None:\n    assert word_count("") == {}\n',
    },
    "go": {
        "fixture": "go",
        "pack": "go",
        "source": "core.go",
        "request": "Add tests for WordCount in core.go, including the empty string case.",
        "test": 'package core\n\nimport "testing"\n\n'
        "func TestWordCountEmptyCodewright(t *testing.T) {\n"
        '\tif got := WordCount(""); len(got) != 0 {\n'
        '\t\tt.Errorf("WordCount(empty) = %v, want empty", got)\n\t}\n}\n',
    },
    "typescript": {
        "fixture": "typescript",
        "pack": "typescript",
        "source": "src/core.ts",
        "request": "Add tests for wordCount in src/core.ts, including the empty string case.",
        "test": 'import { describe, it, expect } from "vitest";\nimport { wordCount } from "./core";\n\n'
        'describe("wordCount", () => {\n'
        '  it("returns nothing for an empty string", () => {\n    expect(wordCount("")).toEqual({});\n  });\n'
        "});\n",
    },
    "javascript": {
        "fixture": "javascript",
        "pack": "javascript",
        "source": "src/core.js",
        "request": "Add tests for wordCount in src/core.js, including the empty string case.",
        "test": 'import { describe, it, expect } from "vitest";\nimport { wordCount } from "./core.js";\n\n'
        'describe("wordCount", () => {\n'
        '  it("returns nothing for an empty string", () => {\n    expect(wordCount("")).toEqual({});\n  });\n'
        "});\n",
    },
    "cpp": {
        "fixture": "cpp",
        "pack": "cpp",
        "source": "src/core.cpp",
        "request": "Add tests for word_count in src/core.cpp, including the empty string case.",
        "test": '#include "miniapp/core.hpp"\n#include <gtest/gtest.h>\n\n'
        'TEST(Codewright, WordCountEmpty) {\n  EXPECT_EQ(miniapp::word_count("").size(), 0u);\n}\n',
    },
}


def fenced(text: str) -> str:
    return f"```\n{text}\n```"


class RealServices:
    """`RunServices` for this test: real events are dropped, the LLM is scripted, every project id hands back the
    one real-sandbox workspace (`tests` works directly on the run's own project)."""

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
        raise NotImplementedError("tests does not use an agent loop")

    def project(self, project_id: str) -> RealProject:
        return self._project

    async def create_project(self, run_id: str, name: str) -> str:
        raise AssertionError("tests should not need a new project in this test")


@pytest.mark.parametrize("lang", sorted(CASES))
async def test_tests_playbook_writes_and_verifies_the_new_test(
    lang: str, workspace: tuple[SandboxClient, str, Path]
) -> None:
    client, ws, work = workspace
    case = CASES[lang]
    shutil.copytree(FIXTURES / case["fixture"], work, dirs_exist_ok=True)
    sid = await start_session(client, ws, work)
    # `_chown`'d to the sandbox's UID; `targets`/`publish` run `git` from this process, as a different one.
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(work)], check=True)  # noqa: S603, S607
    try:
        project = RealProject(client, sid, work)
        llm_client, _bodies = llm_returning(fenced(case["test"]))
        services = RealServices(project, llm_client)
        state = initial_state("tests", work, request=case["request"])
        final, prompts = await drive(compiled("tests", services), cfg(), state, approve_all)  # type: ignore[arg-type]
        assert gates_of(prompts) == ["approve_result"]
        assert final["targets"] and final["targets"][0]["path"] == case["source"], final["targets"]
        test_path = own_test_file(case["pack"], case["source"])
        assert final["written"] == [test_path], final.get("skipped")
        assert final["skipped"] == {}
        branch = final["published"]["branch"]
        assert branch.startswith("codewright/tests-")
        assert git(work, "branch", "--show-current").strip() == branch
        assert test_path in git(work, "show", "--stat", "--format=", "HEAD")
    finally:
        await client.delete_session(sid)
