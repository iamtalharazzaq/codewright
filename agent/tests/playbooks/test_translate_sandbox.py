"""Translate (CODEWRIGHT.md 5.16) end to end in the real sandbox runner (`make check-sandbox`; skipped otherwise):
a small Python CLI is translated into C++ and its compiled binary is checked against the same black-box cases
captured by running the Python original — the Phase 18 acceptance test. Only the model is scripted (its answers are
known-good C++, since this proves the pipeline and the sandbox, not the model); survey's run of the original, the
CMake build of the translation and the black-box comparison are all real.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from agent.language_packs import detect_project
from agent.language_packs.base import Step
from agent.language_packs.executor import run_action, run_step
from agent.llm.client import LLMClient
from agent.playbooks.translate import graph
from agent.tests.playbooks.helpers import initial_state, llm_returning
from agent.tests.sandbox_harness import _chown, _workspaces
from agent.tests.sandbox_harness import start_session as _session
from agent.tools.sandbox import SandboxClient

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(os.environ.get("SANDBOX_TESTS") != "1", reason="needs the sandbox runner: make check-sandbox"),
]

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
MAIN_CPP = """#include <cstdlib>
#include <iostream>

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cout << "usage: calc <a> <b>" << std::endl;
        return 1;
    }
    std::cout << add(std::atoi(argv[1]), std::atoi(argv[2])) << std::endl;
    return 0;
}
"""
CALC_GO = """package main

import (
	"fmt"
	"os"
	"strconv"
)

func add(a int, b int) int {
	return a + b
}

func main() {
	if len(os.Args) != 3 {
		fmt.Println("usage: calc <a> <b>")
		os.Exit(1)
	}
	a, _ := strconv.Atoi(os.Args[1])
	b, _ := strconv.Atoi(os.Args[2])
	fmt.Println(add(a, b))
}
"""
ADD_PY = "def add(a: int, b: int) -> int:\n    return a + b\n"
MAIN_PY = (
    "import sys\n\n\ndef main() -> None:\n"
    '    if len(sys.argv) != 3:\n        print("usage: calc <a> <b>")\n        sys.exit(1)\n'
    "    print(add(int(sys.argv[1]), int(sys.argv[2])))\n"
)


async def _events(_: dict[str, Any]) -> None:
    return None


class RealProject:
    """`ProjectTools`'s sandbox-backed methods, for driving `translate`'s nodes against the real sandbox runner."""

    def __init__(self, client: SandboxClient, sid: str, work: Path) -> None:
        self._client = client
        self._sid = sid
        self._work = work

    @property
    def work(self) -> Path:
        return self._work

    async def sandbox(self, action: str, paths: list[str] | None = None) -> list[dict[str, Any]]:
        components = [c for c in detect_project(self._work) if paths is None or c.path in paths]
        out: list[dict[str, Any]] = []
        for component in components:
            result = await run_action(self._client, self._sid, self._work, component, action, _events)  # type: ignore[arg-type]
            out += [
                {
                    "component": component.path,
                    "pack": component.pack,
                    "step": s.step,
                    "ok": s.ok,
                    "output": s.output_tail,
                }
                for s in result.steps
            ]
        return out

    async def run_step(self, step: Step) -> dict[str, Any]:
        command, buffer = await run_step(self._client, self._sid, step, _events)
        return {"ok": command.ok, "exit_code": command.exit_code, "output": buffer}

    def files_changed(self, paths: list[str]) -> None:
        # the files were written by this process, not the sandbox's own UID: give the toolchain back write access.
        _chown(self._work)


class RealServices:
    """`RunServices` for this test: real events are dropped, the LLM is scripted, the project is `RealProject`."""

    def __init__(self, project: RealProject, client: LLMClient) -> None:
        self._project = project
        self._client = client

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
        return None

    def llm(self, profile: str, *, run_id: str, step: str, role: str) -> LLMClient:
        return self._client

    def project(self, project_id: str) -> RealProject:
        return self._project


@pytest.fixture
async def workspace() -> AsyncIterator[tuple[SandboxClient, str, Path]]:
    ws = f"sbxtest-{uuid.uuid4().hex[:8]}"
    work = _workspaces() / ws / "work"
    work.mkdir(parents=True)
    client = SandboxClient()
    try:
        yield client, ws, work
    finally:
        await client.close()
        shutil.rmtree(work.parent, ignore_errors=True)


async def test_cli_translation_passes_the_same_blackbox_cases(workspace: tuple[SandboxClient, str, Path]) -> None:
    client, ws, work = workspace
    (work / "requirements.txt").write_text("", encoding="utf-8")
    (work / "calc.py").write_text(CALC_PY, encoding="utf-8")
    sid = await _session(client, ws, work)
    # `_session` chowns the workspace to the sandbox's UID; `survey_node` runs `git` from this process, as a
    # different one, so git has to be told the ownership mismatch is expected.
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(work)], check=True)  # noqa: S603, S607
    try:
        project = RealProject(client, sid, work)
        llm_client, _bodies = llm_returning(
            '{"cases": [{"args": ["2", "3"], "stdin": ""}, {"args": ["10", "-4"], "stdin": ""}]}',  # case proposals
            "int add(int a, int b) {\n    return a + b;\n}\n",  # `add`
            MAIN_CPP,  # `main`
        )
        services = RealServices(project, llm_client)
        state = initial_state("translate", work, request="rewrite calc.py in C++", language="C++")

        survey = await graph.survey_node(services)(state)  # type: ignore[arg-type]
        state = {**state, **survey}
        assert len(survey["units"]) == 2, survey
        assert len(survey["cases"]) == 2, survey

        planned = await graph.plan_node(services)(state)  # type: ignore[arg-type]
        state = {**state, **planned}
        assert planned["can_translate"] is True, planned.get("plan_brief")

        translated = await graph.translate_node(services)(state)  # type: ignore[arg-type]
        state = {**state, **translated}
        assert translated["build_ok"] is True, translated.get("build_error")

        verified = await graph.verify_node(services)(state)  # type: ignore[arg-type]
        verification = verified["verification"]
        assert verification["checked"] is True, verification
        assert verification["ok"] is True, verification
        assert verification["passing"] == verification["cases"] == 2, verification
    finally:
        await client.delete_session(sid)


async def test_go_cli_translated_to_python_passes_the_same_blackbox_cases(
    workspace: tuple[SandboxClient, str, Path],
) -> None:
    """A second real language pair (Phase 18's "more language pairs" follow-up): a Go CLI translated into Python,
    the mirror image of the Python->C++ pair above - proves the inventory/target/builder machinery isn't
    accidentally Python-or-C++-specific."""
    client, ws, work = workspace
    (work / "go.mod").write_text("module calc\n\ngo 1.22\n", encoding="utf-8")
    (work / "calc.go").write_text(CALC_GO, encoding="utf-8")
    sid = await _session(client, ws, work)
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(work)], check=True)  # noqa: S603, S607
    try:
        project = RealProject(client, sid, work)
        llm_client, _bodies = llm_returning(
            '{"cases": [{"args": ["2", "3"], "stdin": ""}, {"args": ["10", "-4"], "stdin": ""}]}',
            ADD_PY,
            MAIN_PY,
        )
        services = RealServices(project, llm_client)
        state = initial_state("translate", work, request="rewrite calc.go in Python", language="Python")

        survey = await graph.survey_node(services)(state)  # type: ignore[arg-type]
        state = {**state, **survey}
        assert len(survey["units"]) == 2, survey
        assert len(survey["cases"]) == 2, survey

        planned = await graph.plan_node(services)(state)  # type: ignore[arg-type]
        state = {**state, **planned}
        assert planned["can_translate"] is True, planned.get("plan_brief")

        translated = await graph.translate_node(services)(state)  # type: ignore[arg-type]
        state = {**state, **translated}
        assert translated["build_ok"] is True, translated.get("build_error")

        verified = await graph.verify_node(services)(state)  # type: ignore[arg-type]
        verification = verified["verification"]
        assert verification["checked"] is True, verification
        assert verification["ok"] is True, verification
        assert verification["passing"] == verification["cases"] == 2, verification
    finally:
        await client.delete_session(sid)
