"""Security review (CODEWRIGHT.md Section 5.8) as a whole run, with a fake project and model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.tests.conftest import FakeProject, FakeServices
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tests.playbooks.test_code_playbooks import GREEN, fenced, repo

PYPROJECT = '[project]\nname = "x"\nversion = "0.1.0"\n'
LEAKY = 'AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n\ndef handler():\n    return AWS_KEY\n'
FIXED = "def handler():\n    return load_from_env()\n"

PIP_AUDIT = {
    "dependencies": [
        {"name": "old-pkg", "version": "1.0.0", "vulns": [{"id": "CVE-2024-0001", "fix_versions": ["1.0.1"]}]}
    ]
}
AUDIT_OUTPUTS = [
    {"component": ".", "pack": "python", "step": "install", "ok": True, "exit_code": 0, "output": ""},
    {
        "component": ".",
        "pack": "python",
        "step": "pip-audit",
        "ok": False,
        "exit_code": 1,
        "output": json.dumps(PIP_AUDIT),
    },
]


def _project(tmp_path: Path, audit_outputs: list[dict[str, Any]] | None = None) -> FakeProject:
    work = repo(tmp_path, {"pyproject.toml": PYPROJECT, "app.py": LEAKY})
    return FakeProject(
        work, test_results=[[GREEN]], audit_outputs=AUDIT_OUTPUTS if audit_outputs is None else audit_outputs
    )


async def test_a_pure_review_reports_findings_and_changes_nothing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    services = FakeServices(project=project)
    state, prompts = await drive(
        compiled("security", services),
        cfg(),
        initial_state("security", tmp_path, request="review this for vulnerabilities", use_llm=False),
        approve_all,
    )
    assert gates_of(prompts) == ["approve_result"]  # tier 1: no plan gate, nothing to approve a plan for
    problems = {f["problem"] for f in state["findings"]}
    assert any("AKIA" in p or "AWS access key" in p for p in problems)
    assert any("old-pkg" in p and "CVE-2024-0001" in p for p in problems)
    assert state["changed"] == [] and state.get("branch") is None
    assert "review only" in state["result_brief"]
    assert "AKIA" in (project.work / "app.py").read_text(encoding="utf-8")  # untouched


async def test_asked_to_fix_opens_a_branch_and_removes_the_secret(tmp_path: Path) -> None:
    project = _project(tmp_path, audit_outputs=[])  # only the secret is a fixable finding here
    client, _ = llm_returning(fenced(FIXED))
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, prompts = await drive(
        compiled("security", services),
        cfg(),
        initial_state("security", tmp_path, tier=2, request="find and fix the hard-coded secret", use_llm=False),
        approve_all,
    )
    assert gates_of(prompts) == ["approve_plan", "approve_result"]
    assert state["changed"] == ["app.py"]
    assert "AKIA" not in (project.work / "app.py").read_text(encoding="utf-8")
    assert state["published"]["branch"].startswith("codewright/security-")
    assert state["verification"]["rescan_ok"] is True  # the secret scan is clean on the changed file now
