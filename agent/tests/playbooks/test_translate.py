"""Translate (CODEWRIGHT.md 5.16) as a whole run with a fake sandbox and a scripted model, plus its decline paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.playbooks.translate import blackbox, graph
from agent.playbooks.translate.blackbox import Case
from agent.playbooks.translate.target import LANGUAGES
from agent.tests.conftest import FakeProject, FakeServices
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tools.workspace import git

CALC_PY = """import sys


def add(a: int, b: int) -> int:
    return a + b


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: calc <a> <b>")
        sys.exit(1)
    print(add(int(sys.argv[1]), int(sys.argv[2])))


if __name__ == "__main__":
    main()
"""
LIB_PY = "def helper() -> int:\n    return 1\n"


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


# ── pure helpers ───────────────────────────────────────────────────────────
def test_package_name_from_the_component_path() -> None:
    assert graph._package_name("services/calc") == "calc"
    assert graph._package_name(".") == "app"


def test_target_language_reads_the_input_then_the_answers() -> None:
    assert graph._target_language({"language": "go"}) == "Go"
    assert graph._target_language({"answers": [["target language", "C++"]]}) == "C++"
    assert graph._target_language({}) == LANGUAGES[0]


# ── decline paths ────────────────────────────────────────────────────────────
async def test_survey_declines_when_nothing_is_detected(tmp_path: Path) -> None:
    work = repo(tmp_path, {"README.md": "hi\n"})
    services = FakeServices(project=FakeProject(work))
    state = initial_state("translate", tmp_path, request="translate it", language="Go")
    update = await graph.survey_node(services)(state)
    assert update["declined"] and update["units"] == []


async def test_survey_declines_a_library(tmp_path: Path) -> None:
    work = repo(tmp_path, {"requirements.txt": "", "lib.py": LIB_PY})
    services = FakeServices(project=FakeProject(work))
    state = initial_state("translate", tmp_path, request="translate it", path="lib.py", language="Go")
    update = await graph.survey_node(services)(state)
    assert "library" in update["declined"]


async def test_plan_declines_translating_into_the_same_language(tmp_path: Path) -> None:
    work = repo(tmp_path, {"requirements.txt": "", "calc.py": CALC_PY})
    services = FakeServices(project=FakeProject(work))
    state = initial_state(
        "translate", tmp_path, request="rewrite calc.py", path="calc.py", language="Python", use_llm=False
    )
    state = {**state, **await graph.survey_node(services)(state)}
    update = await graph.plan_node(services)(state)
    assert update["can_translate"] is False
    assert "already Python" in update["plan_brief"]


# ── happy path: Python CLI → C++ ──────────────────────────────────────────────
async def test_translates_a_cli_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = repo(tmp_path, {"requirements.txt": "", "calc.py": CALC_PY})
    case = Case("2 3", ["2", "3"], "", 0, "5\n")

    async def fake_prepare(project: Any, spec: Any) -> str:
        return ""

    async def fake_capture(project: Any, spec: Any, proposals: list[Any]) -> tuple[list[Case], list[str]]:
        return [case], []

    async def fake_check(project: Any, spec: Any, cases: list[Case]) -> list[dict[str, Any]]:
        return [{"name": c.name, "ok": True, "expected": {}, "got": {}} for c in cases]

    monkeypatch.setattr(blackbox, "prepare", fake_prepare)
    monkeypatch.setattr(blackbox, "capture", fake_capture)
    monkeypatch.setattr(blackbox, "check", fake_check)

    project = FakeProject(work)
    client, _bodies = llm_returning(
        '{"cases": [{"args": ["2", "3"], "stdin": ""}]}',  # QA Engineer: proposed black-box cases
        "int add(int a, int b) {\n    return a + b;\n}\n",  # Backend Developer: `add`
        "#include <cstdlib>\n#include <iostream>\n\n"
        "int main(int argc, char** argv) {\n"
        "    if (argc != 3) {\n"
        '        std::cout << "usage: calc <a> <b>" << std::endl;\n'
        "        return 1;\n"
        "    }\n"
        "    std::cout << add(std::atoi(argv[1]), std::atoi(argv[2])) << std::endl;\n"
        "    return 0;\n"
        "}\n",  # Backend Developer: `main`
        '{"findings": []}',  # Tech Lead review
    )
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state = initial_state("translate", tmp_path, request="rewrite calc.py in C++", language="C++")
    final, prompts = await drive(compiled("translate", services), cfg(), state, approve_all)

    assert gates_of(prompts) == ["approve_plan", "approve_result"]
    assert final["can_translate"] is True
    assert final["build_ok"] is True
    assert final["verification"]["checked"] is True
    assert final["verification"]["ok"] is True
    assert final["folder"] == "translated/app-cpp"
    assert sorted(final["names"].values()) == ["add", "main"]
    log = git(work, "log", "--format=%s", "-1")
    assert "Translate" in log and "C++" in log
    assert (work / "translated/app-cpp/CMakeLists.txt").is_file()
    assert "int add" in (work / "translated/app-cpp/src/main.cpp").read_text(encoding="utf-8")
