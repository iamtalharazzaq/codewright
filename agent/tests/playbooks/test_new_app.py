"""New app (CODEWRIGHT.md Section 5.17): the stack rules, and whole runs at each size with a fake sandbox."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.language_packs import templates
from agent.language_packs.base import ServiceSpec
from agent.playbooks.new_app import graph as na
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


def test_a_users_qa_answer_does_not_turn_a_terminal_app_into_a_webapp(tmp_path: Path) -> None:
    """Live finding: requirements Q&A almost always mentions "users" ('who is the main user?' -> 'General
    users'), which used to outrank the real "terminal" signal and scaffold a calculator as a full-stack
    Next.js+FastAPI app instead of a CLI."""
    inputs = {
        "request": "make a calculator",
        "card": {"what": "A terminal-based calculator application"},
        "answers": [
            ("Which language? / Who is the main user of this calculator? / Which platform should it run on?",
             "Which language? Python\nWho is the main user of this calculator? General users\n"
             "Which platform should it run on? Terminal"),
        ],
    }  # fmt: skip
    choice = stacks.choose(inputs, root=_library(tmp_path))
    assert choice.kind == "cli"
    assert choice.template == "cli-python"


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


def test_a_runner_that_found_no_tests_is_not_a_pass() -> None:
    empty = {"component": ".", "report": {"ok": True, "passed": 0, "failed": 0}}
    ok, why = na.tests_green([empty])
    assert ok is False and "No tests ran" in why
    assert na.tests_green([{"component": ".", "report": {"ok": True, "passed": 3, "failed": 0}}]) == (True, "")


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
    # Bug: a failing verify step was recorded as "done" (green) like any other step, so the Timeline and the
    # run's own status badge showed it as a clean pass even though its own summary said otherwise.
    assert state["steps"]["verify"]["status"] == "failed"
    assert next(p for p in state["plan"] if p["id"] == "verify")["status"] == "failed"


async def test_passing_tests_with_failing_lint_still_fails_the_step(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    project = FakeProject(work, test_results=[[GREEN]], lint_outputs=[{"ok": False, "output": "E501 line too long"}])
    client, _ = llm_returning(REQS, PLAN, fenced(GAME), fenced(GAME_TEST), "text")
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, _ = await drive(
        compiled("new_app", services),
        cfg(),
        _state(tmp_path, **run_inputs()),
        approve_all,
    )
    assert state["passed"] is True  # the tests themselves are green
    assert state["steps"]["verify"]["status"] == "failed"  # but a failing lint step still fails the step overall


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


# ── what a new app only gets when asked for ──────────────────────────────────
ADD = "Additional things to be added"


def _extras(request: str, *answers: tuple[str, str]) -> stacks.Extras:
    return stacks.extras({"request": request, "answers": [list(a) for a in answers]})


def test_extras_are_off_unless_the_user_asks_and_backend_tests_are_on() -> None:
    assert _extras("Make a calculator") == stacks.Extras(False, False, False, True, False)
    assert _extras("Make a calculator with GitHub Actions").ci is True
    assert _extras("Make it, and set up Graphify").graphify is True
    assert _extras("Make a todo app with unit tests").frontend_tests is True
    assert _extras("Make a todo app with a README").readme is True


def test_the_ticked_boxes_decide_the_extras() -> None:
    both = _extras("Make a todo app", ("x", f"{ADD} README file, Graphify, Test cases (frontend)"))
    assert both == stacks.Extras(False, True, True, False, True)  # no CI, backend tests unticked
    chat_reply = f"Which language? Python\n{ADD} CI workflow (GitHub Actions), Test cases (backend)"
    assert _extras("Make a todo app", ("Which language? / x", chat_reply)) == stacks.Extras(
        True, False, False, True, False
    )
    assert _extras("Make a todo app", ("x", f"{ADD} ")).backend_tests is False  # nothing ticked
    assert _extras("Make a todo app with CI", ("x", f"{ADD} README file")).ci is False  # the boxes win


def test_the_chosen_frontend_picks_the_template_and_says_when_it_changes_the_language() -> None:
    fe = "Which frontend?"
    inputs = {"request": "Make a todo app", "answers": [["x", "Which language? Python\n" + fe + " React + TypeScript"]]}
    choice = stacks.choose(inputs)
    assert choice.template == "web-react-ts" and "not Python" in choice.note
    js = {
        "request": "Make a todo app",
        "answers": [["x", "Which language? JavaScript\n" + fe + " Next.js (JavaScript)"]],
    }
    assert stacks.choose(js).template == "site-nextjs-js"
    none = {"request": "Make a todo app", "answers": [["x", "Which language? Python\n" + fe + " None"]]}
    assert stacks.choose(none).template == "cli-python"


def _scaffolded(
    tmp_path: Path,
    template: str,
    *,
    ci: bool = True,
    graphify: bool = True,
    frontend_tests: bool = True,
    readme: bool = True,
) -> set[str]:
    spec = ServiceSpec(name="demo", template=template, description="d")
    templates.scaffold(spec, tmp_path / "out", ci=ci, graphify=graphify, frontend_tests=frontend_tests, readme=readme)
    return {p.relative_to(tmp_path / "out").as_posix() for p in (tmp_path / "out").rglob("*") if p.is_file()}


@pytest.mark.parametrize("template", ["web-react-ts", "cli-python", "fullstack-fastapi-nextjs"])
def test_a_new_app_has_no_ci_or_graphify_files_unless_asked(tmp_path: Path, template: str) -> None:
    files = _scaffolded(tmp_path, template, ci=False, graphify=False, frontend_tests=False)
    assert not any(f.startswith(".github/") or f in ("GRAPHIFY.md", "mcp.example.json") for f in files)
    everything = _scaffolded(tmp_path / "all", template)
    assert any(f.startswith(".github/") for f in everything) and "GRAPHIFY.md" in everything


def test_frontend_tests_are_left_out_but_the_backends_tests_stay(tmp_path: Path) -> None:
    react = _scaffolded(tmp_path / "a", "web-react-ts", frontend_tests=False)
    assert not [f for f in react if ".test." in f]
    assert [f for f in _scaffolded(tmp_path / "b", "web-react-ts") if ".test." in f]
    full = _scaffolded(tmp_path / "c", "fullstack-fastapi-nextjs", frontend_tests=False)
    assert not [f for f in full if f.startswith("frontend/") and ".test." in f]
    assert [f for f in full if f.startswith("backend/") and "test" in f]
    assert [f for f in _scaffolded(tmp_path / "d", "cli-python", frontend_tests=False) if f.startswith("tests/")]


def test_the_readme_is_left_out_unless_ticked(tmp_path: Path) -> None:
    assert "README.md" not in _scaffolded(tmp_path / "a", "site-nextjs-ts", readme=False)
    assert "README.md" in _scaffolded(tmp_path / "b", "site-nextjs-ts")


def test_zero_tests_pass_only_for_a_browser_app_nobody_asked_tests_for() -> None:
    empty = [{"component": ".", "report": {"ok": True, "passed": 0, "failed": 0}}]
    assert na.tests_green(empty, need_tests=False) == (True, "")
    assert stacks.expects_tests("web-react-ts", stacks.Extras()) is False
    assert stacks.expects_tests("web-react-ts", stacks.Extras(frontend_tests=True)) is True
    assert stacks.expects_tests("cli-python", stacks.Extras()) is True
    assert stacks.expects_tests("cli-python", stacks.Extras(backend_tests=False)) is False
    assert stacks.expects_tests("fullstack-fastapi-nextjs", stacks.Extras()) is True
    assert stacks.expects_tests("fullstack-fastapi-nextjs", stacks.Extras(backend_tests=False)) is False


def test_a_browser_request_in_a_language_without_a_browser_template_says_it_is_a_terminal_app() -> None:
    python = stacks.choose({"request": "Make a calculator", "language": "Python"})
    assert python.template == "cli-python" and "no browser template for Python" in python.note
    assert stacks.choose({"request": "Make a calculator", "language": "TypeScript"}).note == ""


def test_the_failure_log_goes_to_a_report_not_the_chat_card() -> None:
    log = na.failure_report(
        "src/a.test.js: expected 1 to be null", [{"step": "tsc", "output": "calc.ts(46,13): error TS2322"}]
    )
    assert "expected 1 to be null" in log and "TS2322" in log and log.startswith("# What failed")
    state = {
        "requirements": {"title": "Calc", "summary": "s"},
        "choice": {"label": "React", "template": "web-react-js", "note": ""},
        "passed": False,
        "failure": "very long failing test output " * 40,
        "written": ["a"],
    }
    brief = na._brief(state)  # type: ignore[arg-type]
    assert "Report tab" in brief and "very long failing" not in brief


def test_test_code_inside_app_source_is_found_but_test_files_are_not(tmp_path: Path) -> None:
    files = {
        "src/lib/calc.js": "import { describe, it } from 'vitest';\nexport const add = (a, b) => a + b;\n",
        "src/lib/calc.test.js": "import { describe, it } from 'vitest';\n",
        "src/App.jsx": "export const App = () => null;\n",
        "tests/test_core.py": "def test_x():\n    pass\n",
        "src/app.py": "def test_helper():\n    pass\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    found = na.misplaced_tests(tmp_path, list(files))
    assert [f.split(":")[0] for f in found] == ["src/lib/calc.js", "src/app.py"]
