"""A cancelled run leaves the project as it found it (`put_back`)."""

from __future__ import annotations

from pathlib import Path

from agent.tests.playbooks.test_code_playbooks import repo
from agent.tools.workspace import git, put_back


def test_a_cancelled_run_is_stashed_and_its_branch_removed(tmp_path: Path) -> None:
    work = repo(tmp_path, {"a.py": "x = 1\n"})
    git(work, "checkout", "-q", "-b", "codewright/feature-1")
    (work / "a.py").write_text("x = 2\n", encoding="utf-8")
    (work / "new.py").write_text("y = 1\n", encoding="utf-8")
    git(work, "add", "new.py")
    note = put_back(work, "codewright/feature-1", "run-1")
    assert note == "back on main; its unfinished changes are in `git stash`"
    assert (work / "a.py").read_text(encoding="utf-8") == "x = 1\n" and not (work / "new.py").exists()
    assert "codewright/feature-1" not in git(work, "branch") and "cancelled run run-1" in git(work, "stash", "list")


def test_committed_work_keeps_its_branch_and_another_branch_is_left_alone(tmp_path: Path) -> None:
    work = repo(tmp_path, {"a.py": "x = 1\n"})
    git(work, "checkout", "-q", "-b", "codewright/upgrade-1")
    (work / "a.py").write_text("x = 2\n", encoding="utf-8")
    git(work, "commit", "-q", "-am", "upgrade")
    assert put_back(work, "codewright/other", "r") == ""  # not on that branch: nothing touched
    assert put_back(work, "codewright/upgrade-1", "r") == "back on main"
    assert "codewright/upgrade-1" in git(work, "branch")
