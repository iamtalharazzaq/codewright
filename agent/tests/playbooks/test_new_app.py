"""New app (CODEWRIGHT.md Section 5.17): the stack rules, and whole runs at each size with a fake sandbox."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.language_packs import templates
from agent.playbooks.new_app import stacks
from agent.playbooks.registry import get_playbook
from agent.tests.conftest import FakeProject, FakeServices
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tests.playbooks.test_code_playbooks import GREEN, RED, fenced
from agent.tools.workspace import git

REQS = {
    "title": "Tic Tac Toe",
    "summary": "Two players take turns on a 3x3 grid.",
    "features": ["Play on a 3x3 grid", "Detect a win or a draw"],
    "stories": ["As a player, I want to see who won."],
    "criteria": ["Three in a row wins", "A full board without a winner is a draw"],
    "screens": ["Board: the grid and whose turn it is"],
}
PLAN = {
    "goal": "Play tic tac toe",
    "steps": [
        {"file": "src/lib/game.ts", "change": "winner() and isDraw()", "new": True},
        {"file": "src/lib/game.test.ts", "change": "test both criteria", "new": True},
    ],
    "architecture": "A pure game module and a React board.",
    "data_model": [],
}
GAME = "export const winner = (b: string[]) => null;\nexport const isDraw = (b: string[]) => false;\n"
GAME_TEST = "import { it, expect } from 'vitest';\nit('x', () => expect(1).toBe(1));\n"


def run_inputs(**extra: object) -> dict[str, object]:
    return {"request": "Make a tic-tac-toe game", "language": "TypeScript", **extra}


# ── the stack rules ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("request_text", "language", "template", "size"),
    [
        ("Make a tic-tac-toe game", "", "web-react-ts", "small"),
        ("Make a tic-tac-toe game", "JavaScript", "web-react-js", "small"),
        ("Make a calculator", "Go", "cli-go", "small"),
        ("Make a calculator", "C++", "cli-cpp", "small"),
        ("Make a calculator", "Python", "cli-python", "small"),
        ("Create an inventory app for a small shop", "", "fullstack-fastapi-nextjs", "medium"),
        ("Create a clinic appointment booking app", "Go", "fullstack-go-nextjs", "large"),
        ("A landing page for my bakery", "", "site-nextjs-ts", "small"),
        ("An API for orders", "", "api-go", "medium"),
        ("A script that renames files", "", "cli-python", "small"),
    ],
)
def test_the_stack_follows_the_app_type_and_the_users_language(
    request_text: str, language: str, template: str, size: str, tmp_path: Path
) -> None:
    only = {"request": request_text, "language": language}
    choice = stacks.choose(only, root=_library(tmp_path))
    assert (choice.template, choice.size) == (template, size)


def _library(tmp_path: Path) -> Path:
    """The library as the spec lists it (manifests only), so the rules are tested whatever templates exist yet."""
    languages = {"ts": "TypeScript", "js": "JavaScript", "python": "Python", "fastapi": "Python", "go": "Go",
                 "node": "TypeScript", "cpp": "C++"}  # fmt: skip
    for kind in {o.template for k in stacks.KINDS.values() for o in k.options}:
        language = next((v for k, v in languages.items() if kind.split("-")[-1].startswith(k) or f"-{k}-" in kind), "")
        folder = tmp_path / "templates" / "apps" / kind
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "manifest.yaml").write_text(
            f"name: {kind}\nlanguage: {language or 'TypeScript'}\npack: x\n", encoding="utf-8"
        )
    (tmp_path / "templates" / "services").mkdir(exist_ok=True)
    return tmp_path / "templates"


def test_a_missing_template_falls_back_and_says_so(tmp_path: Path) -> None:
    only_one = tmp_path / "templates"
    (only_one / "apps").mkdir(parents=True)
    (only_one / "services").mkdir()
    src = templates.ROOT / "apps" / "web-react-ts"
    import shutil  # noqa: PLC0415

    shutil.copytree(src, only_one / "apps" / "web-react-ts", ignore=shutil.ignore_patterns("node_modules"))
    choice = stacks.choose({"request": "Make a tic-tac-toe game", "language": "JavaScript"}, root=only_one)
    assert choice.template == "web-react-ts" and "isn't in the library yet" in choice.note


def test_an_unsupported_language_is_declined_with_the_closest_stack() -> None:
    choice = stacks.choose({"request": "Make a calculator in Rust"})
    assert "Rust" in choice.note and choice.template in {"web-react-ts", "cli-python"}


def test_the_options_message_recommends_one_with_a_reason() -> None:
    text = stacks.options_text("browser")
    assert "(recommended: it runs in the browser" in text and text.count("recommended") == 1


# ── whole runs ───────────────────────────────────────────────────────────────
def _state(tmp_path: Path, **inputs: Any) -> dict[str, Any]:
    state = dict(initial_state("new_app", tmp_path, **inputs))
    state["project_id"] = None  # the run manager gives a new app no project; the scaffold creates it
    return state


def _empty_project(tmp_path: Path, results: list[list[dict]] | None = None) -> FakeProject:  # type: ignore[type-arg]
    work = tmp_path / "work"
    work.mkdir()
    return FakeProject(work, test_results=results or [[GREEN]])


async def test_a_small_app_is_planned_built_tested_and_committed(tmp_path: Path) -> None:
    project = _empty_project(tmp_path)
    client, _ = llm_returning(REQS, PLAN, fenced(GAME), fenced(GAME_TEST), "Play against a friend on one screen.")
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, prompts = await drive(
        compiled("new_app", services),
        cfg(),
        _state(tmp_path, **run_inputs()),
        approve_all,
    )
    assert gates_of(prompts) == ["approve_result"] and state["tier"] == 1
    assert services.created == ["Tic Tac Toe"] and state["project_id"]
    assert state["choice"]["template"] == "web-react-ts" and state["passed"] is True
    assert (project.work / "src/lib/game.ts").read_text(encoding="utf-8").startswith("export const winner")
    guide = (project.work / "GUIDE.md").read_text(encoding="utf-8")
    assert "Play against a friend" in guide and "npm run dev" in guide  # the run section comes from the manifest
    assert git(project.work, "log", "-1", "--format=%s") == "Build Tic Tac Toe"
    assert "All 3 tests pass" in state["done_summary"] and "is in Projects" in state["done_summary"]


async def test_a_failing_app_is_shown_red_not_hidden(tmp_path: Path) -> None:
    project = _empty_project(tmp_path, [[RED]])
    client, _ = llm_returning(REQS, PLAN, fenced(GAME), fenced(GAME_TEST), "text")
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, _ = await drive(
        compiled("new_app", services),
        cfg(),
        _state(tmp_path, **run_inputs()),
        approve_all,
    )
    assert state["passed"] is False and "Tests still fail" in state["result_brief"]


@pytest.mark.parametrize(
    ("size", "gates"),
    [
        ("small", ["approve_result"]),
        ("medium", ["approve_plan", "approve_result"]),
        ("large", ["approve_requirements", "approve_design", "approve_screens", "approve_result"]),
    ],
)
async def test_the_gates_grow_with_the_size_of_the_app(tmp_path: Path, size: str, gates: list[str]) -> None:
    services = FakeServices(project=_empty_project(tmp_path))
    state, prompts = await drive(
        compiled("new_app", services),
        cfg(),
        _state(tmp_path, **run_inputs(size=size, use_llm=False)),
        approve_all,
    )
    assert gates_of(prompts) == gates
    flow = get_playbook("new_app").spec.flow({"request": "x", "size": size})
    assert [g for g in flow if g.startswith("approve_")] == gates
    assert state["published"]["branch"] == "main"


def test_the_size_sets_the_tier() -> None:
    spec = get_playbook("new_app").spec
    assert [spec.min_tier({"size": s}) for s in ("small", "medium", "large")] == [1, 2, 3]
    assert spec.min_tier({"request": "Create a clinic appointment booking app"}) == 3
