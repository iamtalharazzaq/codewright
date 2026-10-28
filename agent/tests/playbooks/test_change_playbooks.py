"""Refactor and Performance (Phase 9) as whole runs, with a fake model, sandbox, replay and benchmark."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.playbooks.performance.graph import smells_in, verdict
from agent.tests.conftest import FakeProject, FakeServices
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tests.playbooks.test_code_playbooks import GREEN, RED, fenced, repo
from agent.tools.workspace import git

PYPROJECT = '[project]\nname = "x"\nversion = "0.1.0"\n'
LOOPY = (
    "def total(conn, ids):\n    out = 0\n    for i in ids:\n        out += conn.execute('SELECT 1')\n    return out\n"
)
BETTER = "def total(conn, ids):\n    return conn.execute('SELECT 1') * len(ids)\n"
REPLAY_OK = {"ok": True, "error": None, "report": {"counts": {"regression": 0, "exchanges": 12}}}


def bench(p95: float, failed_rate: float = 0.0) -> dict[str, Any]:
    summary = {
        "requests": 100,
        "rps": 5.0,
        "failed_rate": failed_rate,
        "p95_ms": p95,
        "endpoints": [{"endpoint": "GET /items", "avg_ms": p95 / 2, "p95_ms": p95, "max_ms": p95}],
    }
    return {"ok": failed_rate == 0.0, "error": None, "report": {"summary": summary}}


def plan(file: str = "calc.py") -> dict[str, Any]:
    return {"goal": "Simplify", "steps": [{"file": file, "change": "use one call"}], "risks": "none"}


async def test_refactor_plans_changes_tests_each_step_and_replays_the_traffic(tmp_path: Path) -> None:
    work = repo(tmp_path, {"pyproject.toml": PYPROJECT, "calc.py": LOOPY})
    project = FakeProject(
        work, test_results=[[GREEN]], recordings=[{"id": "rec1"}], verifications={"replay": [REPLAY_OK]}
    )
    client, _ = llm_returning(plan(), fenced(BETTER), {"findings": []})
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, prompts = await drive(
        compiled("refactor", services),
        cfg(),
        initial_state("refactor", tmp_path, request="simplify total"),
        approve_all,
    )
    assert gates_of(prompts) == ["approve_plan", "approve_result"]
    assert [o["done"] for o in state["outcomes"]] == [True]
    assert "len(ids)" in (work / "calc.py").read_text(encoding="utf-8")
    assert state["verification"]["behavior"] == {"checked": True, "ok": True, "regressions": 0, "exchanges": 12}
    assert "identical behavior" in state["done_summary"]
    assert state["published"]["branch"].startswith("codewright/refactor-")
    assert git(work, "branch", "--show-current").strip() == state["published"]["branch"]
    assert project.verified == ["replay"]  # the recording already existed: nothing was recorded again


async def test_a_step_that_breaks_the_tests_is_undone(tmp_path: Path) -> None:
    work = repo(tmp_path, {"pyproject.toml": PYPROJECT, "calc.py": LOOPY})
    project = FakeProject(work, test_results=[[GREEN], [RED]])  # green baseline, then red forever
    client, _ = llm_returning(plan(), fenced("def total(conn, ids):\n    return 0"), {"findings": []})
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, _ = await drive(
        compiled("refactor", services), cfg(), initial_state("refactor", tmp_path, request="simplify"), approve_all
    )
    assert [o["done"] for o in state["outcomes"]] == [False]
    assert (work / "calc.py").read_text(encoding="utf-8") == LOOPY  # exactly as it was
    assert state["changed"] == [] and "Nothing was changed" in state["done_summary"]
    assert "not replayed" in state["result_brief"] or "No change was made" in state["result_brief"]


async def test_refactor_without_a_runnable_app_says_replay_was_not_done(tmp_path: Path) -> None:
    work = repo(tmp_path, {"pyproject.toml": PYPROJECT, "calc.py": LOOPY})
    project = FakeProject(work, test_results=[[GREEN]])  # no recordings, record/replay cannot run
    client, _ = llm_returning(plan(), fenced(BETTER), {"findings": []})
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, _ = await drive(
        compiled("refactor", services), cfg(), initial_state("refactor", tmp_path, request="simplify"), approve_all
    )
    assert state["verification"]["behavior"]["checked"] is False
    assert "Behavior not replayed" in state["result_brief"]


async def test_performance_benchmarks_before_and_after_and_reports_the_gain(tmp_path: Path) -> None:
    work = repo(tmp_path, {"pyproject.toml": PYPROJECT, "calc.py": LOOPY})
    project = FakeProject(
        work,
        test_results=[[GREEN]],
        recordings=[{"id": "rec1"}],
        hits=[{"path": "calc.py", "start_line": 1, "end_line": 5, "content": "total"}],
        verifications={"bench": [bench(200.0), bench(80.0)], "replay": [REPLAY_OK]},
    )
    client, _ = llm_returning(plan(), fenced(BETTER), {"findings": []})
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, prompts = await drive(
        compiled("performance", services),
        cfg(),
        initial_state("performance", tmp_path, request="items is slow"),
        approve_all,
    )
    assert gates_of(prompts) == ["approve_plan", "approve_result"]
    assert project.verified in (["bench", "bench", "replay"], ["bench", "replay", "bench"])
    assert state["comparison"]["p95_ms"]["change_pct"] == -60.0
    assert "✅ **Faster:** p95 200.0 → 80.0 ms (-60.0%)" in state["done_summary"]
    assert state["published"]["branch"].startswith("codewright/perf-")


def test_the_verdict_never_claims_a_gain_that_was_not_measured() -> None:
    assert "not measured" in verdict(None)
    flat = {"p95_ms": {"before": 100, "after": 98, "change_pct": -2.0}, "endpoints": []}
    assert "Not measurably faster" in verdict(flat)


def test_static_scan_finds_the_usual_causes() -> None:
    assert smells_in(LOOPY) == ["a query inside a loop (N+1)"]
    assert smells_in(BETTER) == []
    assert "a pause or sleep" in smells_in("import time\ntime.sleep(1)\n")


async def test_a_rate_limiter_rejecting_the_benchmarks_own_load_is_reported_not_measured(tmp_path: Path) -> None:
    work = repo(tmp_path, {"pyproject.toml": PYPROJECT, "calc.py": LOOPY})
    project = FakeProject(
        work,
        test_results=[[GREEN]],
        recordings=[{"id": "rec1"}],
        hits=[{"path": "calc.py", "start_line": 1, "end_line": 5, "content": "total"}],
        verifications={"bench": [bench(0.5, failed_rate=0.97)]},
    )
    client, _ = llm_returning(plan(), fenced(BETTER), {"findings": []})
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, _ = await drive(
        compiled("performance", services),
        cfg(),
        initial_state("performance", tmp_path, request="items is slow"),
        approve_all,
    )
    assert state["bench_before"] is None and "rate limiter" in state.get("bench_note", "")
    assert "Not measured" in state["plan_brief"]
