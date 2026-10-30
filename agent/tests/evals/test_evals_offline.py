"""Phase 20 evals that need no model: the scoreboard reads real result files, and the review grader scores the
seeded repos from canned findings (a regression in either shows up in CI without a GPU)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals import examples, new_app, review, run_metrics, scoreboard

ROOT = Path(__file__).resolve().parents[3]


def test_the_scoreboard_reads_the_newest_file_of_each_suite(tmp_path: Path) -> None:
    (tmp_path / "router-20261001-000000.json").write_text(json.dumps([{"ok": False}]))
    (tmp_path / "router-20261002-000000.json").write_text(json.dumps([{"ok": True}, {"ok": True}, {"ok": False}]))
    (tmp_path / "write_code-20261002-000000.json").write_text(
        json.dumps(
            [{"passed": True, "language": "Go", "seconds": 10}, {"passed": False, "language": "Python", "seconds": 20}]
        )
    )
    table = scoreboard.render(tmp_path)
    assert "router" in table and "2/3" in table and "67%" in table
    assert "write_code" in table and "1/2" in table and "Go 1/1" in table and "15.0" in table


def test_the_scoreboard_on_the_recorded_results_has_a_line_per_suite() -> None:
    table = scoreboard.render(ROOT / "evals" / "results")
    for suite in ("router", "write_code", "explain", "review-seeded-go", "review-seeded-python"):
        assert suite in table


def test_the_review_grader_finds_a_seeded_issue_and_flags_a_false_alarm() -> None:
    spec = json.loads((ROOT / "evals" / "data" / "review" / "seeded-python.json").read_text())
    repo = ROOT / spec["repo"]
    first = spec["issues"][0]
    line = review.line_of(repo, first["file"], first["at"])
    findings = [
        {"file": first["file"], "line": line, "severity": "critical", "problem": "SQL injection via f-string"},
        {"file": spec["clean"][0], "line": 1, "severity": "major", "problem": "invented problem"},
    ]
    graded = review.grade(spec, repo, findings, window=3)
    assert graded["issues"][0]["found"] and graded["issues"][0]["severity_ok"]
    assert not any(i["found"] for i in graded["issues"][1:])
    assert len(graded["false_alarms"]) == 1


def test_run_metrics_count_success_without_cancelled_runs() -> None:
    def run(id: str, status: str, end: str = "2026-01-01T00:10:00+00:00") -> dict[str, object]:
        return {
            "id": id,
            "playbook": "feature",
            "status": status,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": end,
        }

    runs = [
        run("a", "completed"),
        run("b", "failed"),
        run("c", "cancelled"),
        run("d", "completed", "2026-01-01T00:20:00+00:00"),
    ]
    details: dict[str, dict[str, Any]] = {
        "a": {"approvals": [1, 2], "retries": 2, "usage": {"llm_calls": 10}},
        "d": {"approvals": [], "usage": {"llm_calls": 20}},
    }
    m = run_metrics.summarize(runs, details)["feature"]
    assert (m["runs"], m["completed"], m["failed"], m["cancelled"]) == (4, 2, 1, 1)
    assert (
        round(m["success"], 2) == 0.67
        and m["minutes"] == 15
        and m["approvals"] == 1
        and m["llm_calls"] == 15
        and m["retries"] == 1
    )
    assert "feature" in run_metrics.render({"feature": m})


def test_new_app_acceptance_finds_a_missing_feature_and_test_code_in_source() -> None:
    case = {"must": ["divide", "<button"], "behavior": ["zero"]}
    good = {"src/App.jsx": "<button>divide</button> // zero", "src/App.test.jsx": "import { it } from 'vitest'"}
    assert new_app.grade(case, good, tests_passed=True)["ok"]
    bad = {"src/App.jsx": "<button>add</button>", "src/lib/calc.js": "import { describe } from 'vitest'"}
    graded = new_app.grade(case, bad, tests_passed=True)
    assert not graded["ok"] and graded["missing"] == ["divide"] and graded["tests_in_source"] == ["src/lib/calc.js"]
    assert not new_app.grade(case, good, tests_passed=False)["ok"]
    assert new_app.source_of({"a.py": "x", "tests/test_a.py": "y", "node_modules/x.js": "z"}) == {"a.py": "x"}


def test_examples_md_requests_are_found_and_graded_on_checks_2_to_4() -> None:
    rows = examples.requests_in((ROOT / "EXAMPLES.md").read_text(encoding="utf-8"))
    assert len(rows) >= 60 and any(r[1] == "Make a calculator" for r in rows)

    def msg(role: str, kind: str, content: str = "", **data: Any) -> dict[str, Any]:
        return {"role": role, "kind": kind, "content": content, "data": data, "run_id": None}

    ask = {"question": "Which language?", "default": "Python"}
    good = [msg("user", "text"), msg("assistant", "questions", questions=[ask]), msg("assistant", "confirm")]
    assert examples.passed(examples.grade(good, started_run=False))
    assert not examples.passed(examples.grade(good, started_run=True))  # a run began without Start
    no_language = [msg("assistant", "questions", questions=[{"question": "Which style?", "default": "x"}])]
    assert not examples.grade([*no_language, msg("assistant", "confirm")], False)["language_asked_or_declined"]
    declined = [msg("assistant", "decline", "PHP isn't supported. I can build it in Python.")]
    named = [msg("assistant", "confirm")]
    assert examples.passed(examples.grade(named, started_run=False, request="Reverse a linked list in Go"))
    assert examples.passed(examples.grade(declined, started_run=False))
