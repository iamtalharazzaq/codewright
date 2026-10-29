"""Bug fix (CODEWRIGHT.md 5.7) end to end in the real sandbox runner (`make check-sandbox`; skipped otherwise), for
every language: locate, reproduce, fix (Reflection loop), review and publish all run for real against the shared
mini-app fixtures' own `avg()` bug (every fixture has the same off-by-one divisor, uncovered by its existing
tests). Only the model is scripted (a known-good reproduction test and fix per language), since this proves the
pipeline and the sandbox, not the model.
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

# Per language: the bug report (names the exact file so `locate` finds it without depending on search ranking),
# a reproduction test for Codewright's own test file, and the complete fixed source file.
CASES: dict[str, dict[str, str]] = {
    "python": {
        "fixture": "python",
        "pack": "python",
        "source": "src/miniapp/core.py",
        "report": "avg() in src/miniapp/core.py returns the wrong value: avg([2, 4]) should be 3 but the divisor "
        "is off by one.",
        "test": "from miniapp.core import avg\n\n\ndef test_avg_codewright_is_correct() -> None:\n"
        "    assert avg([2, 4]) == 3\n",
        "fixed": '"""The program\'s logic: plain functions, no input/output, so they are easy to test."""\n\n'
        "from __future__ import annotations\n\n\n"
        'def greet(name: str) -> str:\n    name = name.strip() or "world"\n    return f"Hello, {name}!"\n\n\n'
        "def word_count(text: str) -> dict[str, int]:\n"
        '    """How often each word appears, most frequent first (ties alphabetical)."""\n'
        "    counts: dict[str, int] = {}\n    for word in text.lower().split():\n"
        '        word = word.strip(".,;:!?\\"\'()[]")\n        if word:\n'
        "            counts[word] = counts.get(word, 0) + 1\n"
        "    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))\n\n\n"
        "def avg(nums: list[float]) -> float:\n"
        '    """The arithmetic mean of a list of numbers."""\n    return sum(nums) / len(nums)\n',
    },
    "go": {
        "fixture": "go",
        "pack": "go",
        "source": "core.go",
        "report": "avg() in core.go returns the wrong value: Avg([]float64{2, 4}) should be 3 but the divisor is "
        "off by one.",
        "test": 'package core\n\nimport "testing"\n\n'
        "func TestAvgCodewright(t *testing.T) {\n"
        "\tif got := Avg([]float64{2, 4}); got != 3 {\n"
        '\t\tt.Errorf("Avg([2,4]) = %v, want 3", got)\n\t}\n}\n',
        "fixed": "// Package core holds the program's logic: plain functions, easy to test.\npackage core\n\n"
        'import (\n\t"sort"\n\t"strings"\n)\n\n'
        "func Greet(name string) string {\n\tname = strings.TrimSpace(name)\n"
        '\tif name == "" {\n\t\tname = "world"\n\t}\n\treturn "Hello, " + name + "!"\n}\n\n'
        "// WordCount counts how often each word appears in text.\n"
        "func WordCount(text string) map[string]int {\n\tcounts := map[string]int{}\n"
        "\tfor _, word := range strings.Fields(strings.ToLower(text)) {\n"
        '\t\tword = strings.Trim(word, ".,;:!?\\"\'()[]")\n'
        '\t\tif word != "" {\n\t\t\tcounts[word]++\n\t\t}\n\t}\n\treturn counts\n}\n\n'
        "// WordCountOrder returns WordCount's keys, most frequent first (ties alphabetical).\n"
        "func WordCountOrder(counts map[string]int) []string {\n"
        "\tkeys := make([]string, 0, len(counts))\n\tfor k := range counts {\n\t\tkeys = append(keys, k)\n\t}\n"
        "\tsort.Slice(keys, func(i, j int) bool {\n"
        "\t\tif counts[keys[i]] != counts[keys[j]] {\n\t\t\treturn counts[keys[i]] > counts[keys[j]]\n\t\t}\n"
        "\t\treturn keys[i] < keys[j]\n\t})\n\treturn keys\n}\n\n"
        "// Avg is the arithmetic mean of a list of numbers.\n"
        "func Avg(nums []float64) float64 {\n\tsum := 0.0\n\tfor _, n := range nums {\n\t\tsum += n\n\t}\n"
        "\treturn sum / float64(len(nums))\n}\n",
    },
    "typescript": {
        "fixture": "typescript",
        "pack": "typescript",
        "source": "src/core.ts",
        "report": "avg() in src/core.ts returns the wrong value: avg([2, 4]) should be 3 but the divisor is off "
        "by one.",
        "test": 'import { describe, it, expect } from "vitest";\nimport { avg } from "./core";\n\n'
        'describe("avg", () => {\n  it("is the arithmetic mean", () => {\n    expect(avg([2, 4])).toBe(3);\n'
        "  });\n});\n",
        "fixed": "/** The program's logic: plain functions, easy to test. */\n\n"
        "export function greet(name: string): string {\n"
        '  const trimmed = name.trim() || "world";\n  return `Hello, ${trimmed}!`;\n}\n\n'
        "/** How often each word appears, most frequent first (ties alphabetical). */\n"
        "export function wordCount(text: string): Record<string, number> {\n"
        "  const counts: Record<string, number> = {};\n"
        "  for (const raw of text.toLowerCase().split(/\\s+/)) {\n"
        '    const word = raw.replace(/^[.,;:!?"\'()[\\]]+|[.,;:!?"\'()[\\]]+$/g, "");\n'
        "    if (word) counts[word] = (counts[word] ?? 0) + 1;\n  }\n"
        "  return Object.fromEntries(Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])"
        "));\n}\n\n"
        "/** The arithmetic mean of a list of numbers. */\n"
        "export function avg(nums: number[]): number {\n"
        "  return nums.reduce((a, b) => a + b, 0) / nums.length;\n}\n",
    },
    "javascript": {
        "fixture": "javascript",
        "pack": "javascript",
        "source": "src/core.js",
        "report": "avg() in src/core.js returns the wrong value: avg([2, 4]) should be 3 but the divisor is off "
        "by one.",
        "test": 'import { describe, it, expect } from "vitest";\nimport { avg } from "./core.js";\n\n'
        'describe("avg", () => {\n  it("is the arithmetic mean", () => {\n    expect(avg([2, 4])).toBe(3);\n'
        "  });\n});\n",
        "fixed": "/** The program's logic: plain functions, easy to test. */\n\n"
        "export function greet(name) {\n"
        '  const trimmed = name.trim() || "world";\n  return `Hello, ${trimmed}!`;\n}\n\n'
        "/** How often each word appears, most frequent first (ties alphabetical). */\n"
        "export function wordCount(text) {\n  const counts = {};\n"
        "  for (const raw of text.toLowerCase().split(/\\s+/)) {\n"
        '    const word = raw.replace(/^[.,;:!?"\'()[\\]]+|[.,;:!?"\'()[\\]]+$/g, "");\n'
        "    if (word) counts[word] = (counts[word] ?? 0) + 1;\n  }\n"
        "  return Object.fromEntries(Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])"
        "));\n}\n\n"
        "/** The arithmetic mean of a list of numbers. */\n"
        "export function avg(nums) {\n  return nums.reduce((a, b) => a + b, 0) / nums.length;\n}\n",
    },
    "cpp": {
        "fixture": "cpp",
        "pack": "cpp",
        "source": "src/core.cpp",
        "report": "avg() in src/core.cpp returns the wrong value: avg({2, 4}) should be 3 but the divisor is off "
        "by one.",
        "test": '#include "miniapp/core.hpp"\n#include <gtest/gtest.h>\n\n'
        "TEST(Codewright, AvgIsCorrect) {\n  EXPECT_EQ(miniapp::avg({2, 4}), 3);\n}\n",
        "fixed": '#include "miniapp/core.hpp"\n\n#include <algorithm>\n#include <cctype>\n#include <numeric>\n'
        "#include <sstream>\n\nnamespace miniapp {\n\n"
        "std::string greet(const std::string& name) {\n"
        '  auto start = name.find_first_not_of(" \\t\\n");\n'
        '  auto end = name.find_last_not_of(" \\t\\n");\n'
        '  std::string trimmed = (start == std::string::npos) ? "" : name.substr(start, end - start + 1);\n'
        '  if (trimmed.empty()) trimmed = "world";\n  return "Hello, " + trimmed + "!";\n}\n\n'
        "std::map<std::string, int> word_count(const std::string& text) {\n"
        "  std::map<std::string, int> counts;\n  std::istringstream stream(text);\n  std::string word;\n"
        "  while (stream >> word) {\n    std::string lower;\n"
        "    for (char c : word) lower += static_cast<char>(std::tolower(c));\n"
        "    while (!lower.empty() && std::ispunct(static_cast<unsigned char>(lower.back()))) lower.pop_back();\n"
        "    if (!lower.empty()) counts[lower]++;\n  }\n  return counts;\n}\n\n"
        "double avg(const std::vector<double>& nums) {\n"
        "  double sum = std::accumulate(nums.begin(), nums.end(), 0.0);\n"
        "  return sum / static_cast<double>(nums.size());\n}\n\n}  // namespace miniapp\n",
    },
}


def fenced(text: str) -> str:
    return f"```\n{text}\n```"


class RealServices:
    """`RunServices` for this test: real events are dropped, the LLM is scripted, every project id hands back the
    one real-sandbox workspace (bug_fix works directly on the run's own project)."""

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
        raise NotImplementedError("bug_fix does not use an agent loop")

    def project(self, project_id: str) -> RealProject:
        return self._project

    async def create_project(self, run_id: str, name: str) -> str:
        raise AssertionError("bug_fix should not need a new project in this test")


@pytest.mark.parametrize("lang", sorted(CASES))
async def test_bug_fix_reproduces_and_fixes_the_shared_avg_bug(
    lang: str, workspace: tuple[SandboxClient, str, Path]
) -> None:
    client, ws, work = workspace
    case = CASES[lang]
    shutil.copytree(FIXTURES / case["fixture"], work, dirs_exist_ok=True)
    sid = await start_session(client, ws, work)
    # `_chown`'d to the sandbox's UID; `locate`/`publish` run `git` from this process, as a different one.
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(work)], check=True)  # noqa: S603, S607
    try:
        project = RealProject(client, sid, work)
        llm_client, _bodies = llm_returning(fenced(case["test"]), fenced(case["fixed"]), '{"findings": []}')
        services = RealServices(project, llm_client)
        state = initial_state("bug_fix", work, request=case["report"])
        final, prompts = await drive(compiled("bug_fix", services), cfg(), state, approve_all)  # type: ignore[arg-type]
        assert gates_of(prompts) == ["approve_result"]
        assert final["target"]["path"] == case["source"], final["target"]
        assert final["reproduced"], final.get("failure")
        assert final["fixed"] and final["attempts"] == 1, final.get("result_brief")
        branch = final["published"]["branch"]
        assert branch.startswith("codewright/fix-")
        assert git(work, "branch", "--show-current").strip() == branch
        test_path = own_test_file(case["pack"], case["source"])
        assert case["source"] in git(work, "show", "--stat", "--format=", "HEAD")
        assert test_path in git(work, "show", "--stat", "--format=", "HEAD")
    finally:
        await client.delete_session(sid)
