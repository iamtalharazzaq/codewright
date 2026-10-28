"""Code review core (Phase 6 tasks 2 and 5): grounding findings in the code, severity, merging, linters, the report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.playbooks import review_core as rc
from agent.tests.playbooks.helpers import llm_returning

CODE = """package store

func Search(db *sql.DB, q string) ([]Book, error) {
	query := fmt.Sprintf("SELECT * FROM books WHERE title LIKE '%%%s%%'", q)
	rows, err := db.Query(query)
	if err != nil {
		return nil, err
	}
	return scan(rows), nil
}
"""


def finding(**kw: Any) -> dict[str, Any]:
    base = {"file": "a.go", "line": 4, "severity": "major", "category": "bug", "problem": "x", "source": "tech_lead"}
    return {**base, **kw}


def test_a_finding_moves_to_the_line_its_evidence_is_on() -> None:
    lines = CODE.splitlines()
    chunk = rc.chunks(CODE)[0]
    assert rc.ground({"line": 3, "evidence": 'fmt.Sprintf("SELECT'}, lines, chunk) == 4
    assert rc.ground({"line": 5, "evidence": "rows, err := db.Query(query)"}, lines, chunk) == 5


def test_a_finding_quoting_code_that_isnt_there_is_dropped() -> None:
    lines = CODE.splitlines()
    chunk = rc.chunks(CODE)[0]
    assert rc.ground({"line": 4, "evidence": "if user.IsAdmin() {"}, lines, chunk) is None
    assert rc.ground({"line": 40, "evidence": ""}, lines, chunk) is None  # outside the chunk it was shown
    assert rc.ground({"line": 6, "evidence": ""}, lines, chunk) == 6  # no quote: the cited line, if shown


def test_severity_is_capped_by_category() -> None:
    assert rc.calibrate("critical", "security", "SQL injection through q") == "critical"
    assert rc.calibrate("minor", "security", "Path traversal: name can contain ../") == "major"
    assert rc.calibrate("critical", "security", "The function has no input validation") == "major"
    assert rc.calibrate("critical", "bug", "Index out of range panics on the last loop") == "critical"
    assert rc.calibrate("critical", "bug", "The fee is computed for one day too many") == "major"
    assert rc.calibrate("critical", "error-handling", "The error is ignored") == "major"
    assert rc.calibrate("major", "style", "Name is too long") == "nit"
    assert rc.calibrate("minor", "bug", "x") == "minor"
    cast = "Type assertion bypassing TypeScript safety checks"  # not a run-time hole, even with "bypass" in it
    assert rc.recategorize("security", cast) == "types" and rc.calibrate("critical", "types", cast) == "minor"
    assert rc.recategorize("security", "SQL injection through q") == "security"


def test_merge_keeps_different_problems_on_one_line_and_joins_the_same_one() -> None:
    merged = rc.merge(
        [
            finding(category="security", severity="critical", problem="SQL injection via the q parameter"),
            finding(category="security", problem="SQL injection: q is formatted into the query", source="security"),
            finding(category="security", problem="Server-side request forgery through the URL"),
            finding(line=5, category="error-handling", severity="minor", problem="rows never closed"),
            finding(line=5, category="bug", severity="minor", problem="vet: unused", source="linter:vet"),
            finding(file="b.go", line=1, severity="nit", category="style", problem="naming"),
        ]
    )
    assert [(f["file"], f["line"], f["severity"]) for f in merged] == [
        ("a.go", 4, "critical"),
        ("a.go", 4, "major"),
        ("a.go", 5, "minor"),
        ("b.go", 1, "nit"),
    ]
    assert merged[0]["sources"] == ["security", "tech_lead"]
    assert merged[2]["sources"] == ["linter:vet", "tech_lead"]  # a linter agreeing with the model
    assert [f["id"] for f in merged] == [1, 2, 3, 4]


async def test_review_file_grounds_and_rates_the_models_findings(tmp_path: Path) -> None:
    (tmp_path / "store.go").write_text(CODE, encoding="utf-8")
    reply = {
        "findings": [
            {"line": 3, "evidence": "fmt.Sprintf(\"SELECT", "problem": "SQL injection via q", "why": "data theft",
             "category": "security", "severity": "minor", "fix": "use $1"},
            {"line": 6, "evidence": "os.RemoveAll(dir)", "problem": "deletes files", "why": "data loss",
             "category": "bug", "severity": "critical", "fix": "-"},
        ]
    }  # fmt: skip
    client, bodies = llm_returning(reply)
    usage = rc.ReviewUsage()
    found = await rc.review_file(client, tmp_path, "store.go", role="tech_lead", cache_dir=tmp_path / "c", usage=usage)
    assert [(f["line"], f["severity"]) for f in found] == [(4, "major")]  # moved to its line; floor for an exploit
    assert found[0]["code"].startswith("query := fmt.Sprintf")
    assert usage.calls == 1 and "    4  \tquery" in bodies[0]["messages"][1]["content"]
    again = await rc.review_file(client, tmp_path, "store.go", role="tech_lead", cache_dir=tmp_path / "c")
    assert again == found and len(bodies) == 1  # the cached chunk isn't sent again


async def test_echoed_instructions_are_dropped_and_rambling_is_cut(tmp_path: Path) -> None:
    (tmp_path / "store.go").write_text(CODE, encoding="utf-8")
    long = "The query is built by formatting q into the SQL string. " + "It could also be that the caller " * 20
    reply = {
        "findings": [
            {"line": 4, "evidence": "", "problem": "unvalidated input reaching dangerous calls", "why": "-",
             "category": "security", "severity": "major", "fix": "-"},
            {"line": 4, "evidence": "", "problem": long, "why": "-", "category": "security", "severity": "critical",
             "fix": "-"},
        ]
    }  # fmt: skip
    client, _ = llm_returning(reply)
    found = await rc.review_file(client, tmp_path, "store.go", role="security_engineer")
    assert [f["problem"] for f in found] == ["The query is built by formatting q into the SQL string."]


def test_secrets_in_tests_are_test_data(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app/config.py").write_text('API_KEY = "s3cr3t-value-123"\n', encoding="utf-8")
    fixtures = 'password = "hunter2-test-pw"\ntoken = "t0k3n-for-tests"\n'
    (tmp_path / "app/test_login.py").write_text(fixtures, encoding="utf-8")
    found = {f["file"]: f for f in rc.secret_findings(tmp_path, ["app/config.py", "app/test_login.py"])}
    assert found["app/config.py"]["severity"] == "critical"
    test = found["app/test_login.py"]  # one finding for the file's fixtures
    assert test["severity"] == "minor" and test["problem"] == "2 hard-coded secret values in test data (lines 1, 2)."


def test_linter_output_becomes_findings() -> None:
    outputs = [
        {"step": "vet", "component": "api", "output": "./store/store.go:12:2: unreachable code\nok  \tlib"},
        {"step": "ruff", "component": ".", "output": "app/db.py:22:5: S608 Possible SQL injection\nFound 1 error."},
        {
            "step": "eslint",
            "component": "web",
            "output": "/work/web/src/a.ts\n  3:7  error  'x' is unused  no-unused-vars",
        },
    ]
    found = rc.parse_lint(outputs)
    assert [(f["file"], f["line"], f["severity"], f["category"]) for f in found] == [
        ("api/store/store.go", 12, "major", "bug"),
        ("app/db.py", 22, "major", "security"),
        ("web/src/a.ts", 3, "minor", "bug"),
    ]


def test_scope_by_file_folder_module_or_word(tmp_path: Path) -> None:
    for rel in ("internal/billing/a.go", "internal/billing/a_test.go", "internal/mailer/m.go", "web/app.ts"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x\n", encoding="utf-8")
    modules = ["internal/billing", "internal/mailer", "web"]
    assert rc.resolve_scope(tmp_path, "", modules)[0] == "the whole project"
    assert rc.resolve_scope(tmp_path, "web/app.ts", modules) == ("web/app.ts", ["web/app.ts"])
    assert rc.resolve_scope(tmp_path, "internal/mailer", modules)[1] == ["internal/mailer/m.go"]
    assert rc.resolve_scope(tmp_path, "billing", modules)[1] == ["internal/billing/a.go", "internal/billing/a_test.go"]


def test_summary_and_report() -> None:
    findings = rc.merge(
        [
            finding(category="security", severity="critical", problem="SQL injection", fix="db.Query(q, $1)"),
            finding(line=9, severity="nit", category="style", problem="naming", fix="rename"),
        ]
    )
    summary = rc.summarize(findings, files_reviewed=8)
    assert summary["counts"] == {"critical": 1, "major": 0, "minor": 0, "nit": 1}
    assert summary["score"] == 6.9 and summary["top"][0]["problem"] == "SQL injection"
    md = rc.report_markdown("Code review", "the whole project", findings, summary, ["linters skipped"])
    assert "**Score:** 6.9/10" in md and "## Fix these first" in md and "### 1. `a.go:4`: SQL injection" in md
    assert "## Notes" in md
