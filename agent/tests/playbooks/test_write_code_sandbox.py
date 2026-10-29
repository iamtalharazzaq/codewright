"""Write code (CODEWRIGHT.md 5.1b) end to end in the real sandbox runner (`make check-sandbox`; skipped otherwise),
for every language Write code supports: the scaffold, the write/verify/explain/publish flow and the Reflection
loop's `test()` call all run for real. Only the model is scripted (known-good code and tests per language), since
this proves the pipeline and the sandbox, not the model.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from agent.llm.client import LLMClient
from agent.playbooks.write_code.scaffold import layout
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tests.sandbox_harness import RealProject, start_session
from agent.tools.sandbox import SandboxClient

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(os.environ.get("SANDBOX_TESTS") != "1", reason="needs the sandbox runner: make check-sandbox"),
]

# Known-good "sum a list" solutions and tests, one per language, following `write_code.scaffold.LAYOUTS`'s own
# conventions (file names, test framework, import style) so the real sandbox builds and passes them first try.
LANG_CODE: dict[str, tuple[str, str]] = {
    "Python": (
        "def solve(nums: list[int]) -> int:\n    return sum(nums)\n",
        "from solution import solve\n\n\n"
        "def test_solve_sums_numbers() -> None:\n    assert solve([1, 2, 3]) == 6\n\n\n"
        "def test_solve_empty_list() -> None:\n    assert solve([]) == 0\n",
    ),
    "Go": (
        "package snippet\n\n"
        "func Solve(nums []int) int {\n\tsum := 0\n\tfor _, n := range nums {\n\t\tsum += n\n\t}\n\treturn sum\n}\n",
        'package snippet\n\nimport "testing"\n\n'
        "func TestSolve(t *testing.T) {\n"
        "\tcases := []struct {\n\t\tnums []int\n\t\twant int\n\t}{\n"
        "\t\t{[]int{1, 2, 3}, 6},\n\t\t{[]int{}, 0},\n\t}\n"
        "\tfor _, c := range cases {\n"
        "\t\tif got := Solve(c.nums); got != c.want {\n"
        '\t\t\tt.Errorf("Solve(%v) = %d, want %d", c.nums, got, c.want)\n'
        "\t\t}\n\t}\n}\n",
    ),
    "C++": (
        "#pragma once\n#include <vector>\n\n"
        "inline int solve(const std::vector<int>& nums) {\n"
        "    int sum = 0;\n    for (int n : nums) sum += n;\n    return sum;\n}\n",
        '#include "solution.hpp"\n#include <cassert>\n#include <vector>\n\n'
        "int main() {\n    assert(solve({1, 2, 3}) == 6);\n    assert(solve({}) == 0);\n    return 0;\n}\n",
    ),
    "TypeScript": (
        "export function solve(nums: number[]): number {\n  return nums.reduce((a, b) => a + b, 0);\n}\n",
        'import { describe, it, expect } from "vitest";\nimport { solve } from "./solution";\n\n'
        'describe("solve", () => {\n'
        '  it("sums numbers", () => {\n    expect(solve([1, 2, 3])).toBe(6);\n  });\n'
        '  it("handles an empty list", () => {\n    expect(solve([])).toBe(0);\n  });\n'
        "});\n",
    ),
    "JavaScript": (
        "export function solve(nums) {\n  return nums.reduce((a, b) => a + b, 0);\n}\n",
        'import { describe, it, expect } from "vitest";\nimport { solve } from "./solution.js";\n\n'
        'describe("solve", () => {\n'
        '  it("sums numbers", () => {\n    expect(solve([1, 2, 3])).toBe(6);\n  });\n'
        '  it("handles an empty list", () => {\n    expect(solve([])).toBe(0);\n  });\n'
        "});\n",
    ),
}


def fenced(text: str) -> str:
    return f"```\n{text}\n```"


class RealServices:
    """`RunServices` for this test: real events are dropped, the LLM is scripted, every project id hands back the
    one real-sandbox workspace (Write code builds in its own scratch project, never the run's own)."""

    def __init__(self, project: RealProject, client: LLMClient) -> None:
        self._project = project
        self._client = client

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
        return None

    def llm(self, profile: str, *, run_id: str, step: str, role: str) -> LLMClient:
        return self._client

    def chat_model(self, profile: str, *, run_id: str, step: str, role: str, **kwargs: object) -> object:
        raise NotImplementedError("write_code does not use an agent loop")

    def project(self, project_id: str) -> RealProject:
        return self._project

    async def create_project(self, run_id: str, name: str) -> str:
        raise AssertionError("write_code should not need a new project in this test")


@pytest.mark.parametrize("lang", sorted(LANG_CODE))
async def test_write_code_passes_first_try_for_each_language(
    lang: str, workspace: tuple[SandboxClient, str, Path]
) -> None:
    client, ws, work = workspace
    sid = await start_session(client, ws, work)
    try:
        project = RealProject(client, sid, work)
        code, tests = LANG_CODE[lang]
        llm_client, _bodies = llm_returning(
            fenced(code), fenced(tests), "Sums the list by iterating once. Time: O(n), space: O(1)."
        )
        services = RealServices(project, llm_client)
        state = initial_state("write_code", work, request="sum a list of numbers", language=lang)
        state["project_id"] = None
        final, prompts = await drive(compiled("write_code", services), cfg(), state, approve_all)  # type: ignore[arg-type]
        assert gates_of(prompts) == ["approve_result"]
        assert final["passed"] and final["tried"] == 1, final.get("failure")
        lay = layout(lang)
        assert code.strip() in (work / lay.code).read_text(encoding="utf-8")
        assert "Sums the list" in final["done_summary"]
    finally:
        await client.delete_session(sid)
