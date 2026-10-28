"""Code review (Phase 6 task 5) and Docs (task 3) as whole runs on a small project, with a fake model."""

from __future__ import annotations

import json
from pathlib import Path

from agent.playbooks.docs.graph import _commands_md, check, for_people
from agent.tests.conftest import FakeProject, FakeServices
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_by_task
from agent.tools.workspace import git

STORE = '''"""Items in SQLite."""

import sqlite3


def find(conn: sqlite3.Connection, name: str) -> list[tuple]:
    return conn.execute(f"SELECT * FROM items WHERE name = '{name}'").fetchall()
'''
MAIN = """from fastapi import FastAPI

app = FastAPI()


@app.get("/items/{item_id}")
def read_item(item_id: int) -> dict:
    return {"id": item_id}
"""


def project_dir(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    files = {
        "pyproject.toml": '[project]\nname = "items"\nversion = "0.1.0"\ndependencies = ["fastapi"]\n',
        "app/__init__.py": "",
        "app/store.py": STORE,
        "app/main.py": MAIN,
        "app/clean.py": "def double(x: int) -> int:\n    return 2 * x\n",
    }
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8")
    git(work, "init", "-q", "-b", "main")
    git(work, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git(work, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    return work


async def test_review_of_a_folder_reports_grounded_findings_by_severity(tmp_path: Path) -> None:
    lint = [{"step": "ruff", "component": ".", "output": "app/store.py:7:24: S608 Possible SQL injection"}]
    project = FakeProject(project_dir(tmp_path), lint_outputs=lint)
    finding = {
        "line": 6, "evidence": "conn.execute(f\"SELECT", "problem": "SQL injection through name", "why": "Data theft.",
        "category": "security", "severity": "critical", "fix": "conn.execute('... = ?', (name,))",
    }  # fmt: skip
    client, asked = llm_by_task(
        {"review_tech_lead": {"findings": [finding]}, "review_security_engineer": {"findings": [finding]}}
    )
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    _, prompts = await drive(
        compiled("code_review", services), cfg(), initial_state("code_review", tmp_path, path="app"), approve_all
    )
    assert prompts == []  # tier 0: no gates
    assert "review_security_engineer" in asked  # store.py runs queries: the security pass reads it
    report = json.loads((tmp_path / "runs" / "r1" / "findings.json").read_text(encoding="utf-8"))
    findings = report["findings"]
    assert (findings[0]["file"], findings[0]["line"], findings[0]["severity"]) == ("app/store.py", 7, "critical")
    assert set(findings[0]["sources"]) >= {"tech_lead", "security_engineer"}  # the same problem, merged
    assert report["summary"]["files_reviewed"] == 4  # the folder's files, nothing outside it
    md = (tmp_path / "runs" / "r1" / "review.md").read_text(encoding="utf-8")
    assert "## Critical" in md and "`app/store.py:7`" in md and "Suggested fix" in md


async def test_docs_are_checked_approved_and_committed_on_a_branch(tmp_path: Path) -> None:
    work = project_dir(tmp_path)
    project = FakeProject(work, summary={"name": "items"})
    services = FakeServices(project=project)
    state, prompts = await drive(
        compiled("docs", services), cfg(), initial_state("docs", tmp_path, use_llm=False, docs=["readme", "api"]),
        approve_all,
    )  # fmt: skip
    assert gates_of(prompts) == ["approve_result"]
    assert project.actions == ["build"]  # the documented build ran in the sandbox
    assert state["verification"]["problems"] == []
    branch = state["published"]["branch"]
    assert branch.startswith("codewright/docs-") and git(work, "branch", "--show-current").strip() == branch
    api = (work / state["published"]["files"][1]).read_text(encoding="utf-8")
    assert "/items/" in api  # the endpoint table comes from the code
    assert set(project.changed) == set(state["published"]["files"])


def test_docs_mentioning_what_isnt_there_are_flagged(tmp_path: Path) -> None:
    work = project_dir(tmp_path)
    facts = {"stack": {"components": [{"routes": ["GET /items/{item_id} (app/main.py:6)"]}]}}
    docs = {"api": "Call `GET /items/42` or `POST /orders`. See `app/main.py` and `app/billing.py`."}
    problems = [p["problem"] for p in check(docs, facts, work)]
    assert problems == ["POST /orders is not an endpoint in the code", "`app/billing.py` doesn't exist in the project"]


def test_commands_in_docs_are_for_people() -> None:
    assert for_people("go test -json ./...") == "go test ./..."
    assert for_people("go build -o .codewright/bin/app ./cmd/api") == "go build -o bin/app ./cmd/api"
    vitest = "npx --no-install vitest run --reporter=default --reporter=junit --outputFile.junit=.codewright/r.xml"
    assert for_people(vitest) == "npx --no-install vitest run"
    facts = {
        "commands": [
            {
                "component": ".", "pack": "go", "kind": "api", "port": 8080,
                "build": [{"workdir": ".", "cmd": "go mod download"}, {"workdir": ".", "cmd": "go build ./..."}],
                "test": [{"workdir": ".", "cmd": "go mod download"}, {"workdir": ".", "cmd": "go test -json ./..."}],
                "prepare": [{"workdir": ".", "cmd": "go mod download"},
                            {"workdir": ".", "cmd": "go build -o .codewright/bin/app ./cmd/api"}],
                "start": "./.codewright/bin/app",
            }
        ]
    }  # fmt: skip
    md = _commands_md(facts)
    assert "**Test:**\n\n```sh\ngo test ./...\n```" in md  # the build steps aren't repeated
    assert "**Run (listens on port 8080):**\n\n```sh\ngo build -o bin/app ./cmd/api\n./bin/app\n```" in md
    assert ".codewright" not in md
