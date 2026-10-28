"""Write code, Bug fix and Tests (Phase 8) as whole runs, with a fake model and a fake sandbox."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tests.conftest import FakeProject, FakeServices
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tools.workspace import git

GREEN = {"component": ".", "pack": "python", "ok": True, "report": {"ok": True, "passed": 3, "failed": 0, "cases": []}}
RED = {
    "component": ".",
    "pack": "python",
    "ok": False,
    "report": {
        "ok": False,
        "passed": 1,
        "failed": 1,
        "cases": [{"name": "test_empty", "status": "failed", "message": "assert 0 == 1"}],
    },
}


def fenced(text: str) -> str:
    return f"```python\n{text}\n```"


def repo(tmp_path: Path, files: dict[str, str]) -> Path:
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8")
    git(work, "init", "-q", "-b", "main")
    git(work, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git(work, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    return work


async def test_write_code_fixes_failing_tests_with_the_reflection_loop(tmp_path: Path) -> None:
    work = tmp_path / "scratch" / "work"
    project = FakeProject(work, test_results=[[RED], [GREEN]])
    client, bodies = llm_returning(
        fenced("def reverse(x):\n    return x[::-1]"),  # Code Writer
        fenced("from solution import reverse\n\ndef test_empty():\n    assert reverse([]) == []"),  # Test Writer
        fenced("def reverse(x):\n    return list(reversed(x))"),  # the fix
        "Reverses by walking backwards. Time: O(n), space: O(n).",  # explanation
    )
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state = initial_state("write_code", tmp_path, request="reverse a list", language="Python")
    state["project_id"] = None
    final, prompts = await drive(compiled("write_code", services), cfg(), state, approve_all)
    assert gates_of(prompts) == ["approve_result"]
    assert final["passed"] and final["tried"] == 2
    assert "list(reversed" in (work / "solution.py").read_text(encoding="utf-8")
    assert (work / "pyproject.toml").is_file()  # the scaffold the Language Pack recognizes
    assert "All 3 tests pass" in final["done_summary"] and "O(n)" in final["done_summary"]
    assert "failing" in bodies[2]["messages"][1]["content"].lower() or "assert 0 == 1" in str(bodies[2])  # fed back


async def test_write_code_reports_honestly_when_the_tests_never_pass(tmp_path: Path) -> None:
    project = FakeProject(tmp_path / "w" / "work", test_results=[[RED]])
    client, _ = llm_returning(fenced("def f(): pass"), fenced("def test_f(): assert False"), "Explained.")
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state = initial_state("write_code", tmp_path, request="f", language="Python")
    state["project_id"] = None
    final, _ = await drive(compiled("write_code", services), cfg(), state, approve_all)
    assert not final["passed"] and final["tried"] == 5
    assert "Tests still fail" in final["done_summary"]


async def test_bug_fix_reproduces_then_fixes_and_commits_on_a_branch(tmp_path: Path) -> None:
    work = repo(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "x"\nversion = "0.1.0"\n',
            "calc.py": "def avg(xs):\n    return sum(xs) / (len(xs) + 1)\n",
        },
    )
    hits = [{"path": "calc.py", "start_line": 1, "end_line": 2, "content": "def avg"}]
    # reproduce → red; fix attempt 1 → red; fix attempt 2 → green
    project = FakeProject(work, hits=hits, test_results=[[RED], [RED], [GREEN]])
    client, _ = llm_returning(
        fenced("from calc import avg\n\ndef test_avg():\n    assert avg([2, 4]) == 3"),
        fenced("def avg(xs):\n    return sum(xs) / len(xs) + 1"),
        fenced("def avg(xs):\n    return sum(xs) / len(xs)"),
        {"findings": []},
    )
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    final, prompts = await drive(
        compiled("bug_fix", services), cfg(), initial_state("bug_fix", tmp_path, request="avg is wrong"), approve_all
    )
    assert gates_of(prompts) == ["approve_result"]
    assert final["reproduced"] and final["fixed"] and final["attempts"] == 2
    assert (work / "test_calc_codewright.py").is_file() and "(len(xs) + 1)" not in (work / "calc.py").read_text(
        encoding="utf-8"
    )
    branch = final["published"]["branch"]
    assert branch.startswith("codewright/fix-") and git(work, "branch", "--show-current").strip() == branch
    assert "calc.py" in git(work, "show", "--stat", "--format=", "HEAD")


async def test_tests_playbook_writes_runs_and_shows_before_and_after(tmp_path: Path) -> None:
    work = repo(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "x"\nversion = "0.1.0"\n',
            "calc.py": "def double(x):\n    return 2 * x\n",
        },
    )
    hits: list[dict[str, Any]] = [{"path": "calc.py", "start_line": 1, "end_line": 2, "content": "def double"}]
    project = FakeProject(work, hits=hits, test_results=[[GREEN]])
    client, _ = llm_returning(fenced("from calc import double\n\ndef test_double():\n    assert double(2) == 4"))
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    final, prompts = await drive(
        compiled("tests", services), cfg(), initial_state("tests", tmp_path, request="test calc"), approve_all
    )
    assert gates_of(prompts) == ["approve_result"]
    assert final["written"] == ["test_calc_codewright.py"]
    assert "Before:" in final["result_brief"] and "After:" in final["result_brief"]
    assert final["published"]["branch"].startswith("codewright/tests-")


async def test_tests_that_never_pass_are_dropped_not_committed(tmp_path: Path) -> None:
    work = repo(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "x"\nversion = "0.1.0"\n',
            "calc.py": "def double(x):\n    return 2 * x\n",
        },
    )
    hits: list[dict[str, Any]] = [{"path": "calc.py", "start_line": 1, "end_line": 2, "content": "def double"}]
    project = FakeProject(work, hits=hits, test_results=[[GREEN], [RED]])  # green baseline, then red forever
    client, _ = llm_returning(fenced("def test_broken():\n    assert False"))
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    final, _ = await drive(
        compiled("tests", services), cfg(), initial_state("tests", tmp_path, request="test calc"), approve_all
    )
    assert final["written"] == [] and "test_calc_codewright.py" in final["skipped"]
    assert not (work / "test_calc_codewright.py").exists()  # a failing file would break the project's own run
    assert "dropped" in final["result_brief"]
