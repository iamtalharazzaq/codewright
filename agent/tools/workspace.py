"""Project workspaces (CODEWRIGHT.md Section 8.1).

`workspaces/<project_id>/`:
- `source/`  the imported original, kept as is (Codewright never edits it)
- `work/`    a git repository with the same files; every change happens on a branch here
- `graph/`, `baseline/`, `runs/<run_id>/`, `logs/`  filled by later phases

Delivery publishes a branch of `work/` (or its files).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from agent.tools.secrets import SKIP_DIRS

LAYOUT = ("source", "work", "graph", "baseline", "runs", "logs")

# File extension → language, for the project home. The five supported languages (C12) first.
LANGUAGES = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".go": "Go",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".h": "C/C++",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".php": "PHP",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".swift": "Swift",
    ".sql": "SQL",
}

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Codewright",
    "GIT_AUTHOR_EMAIL": "codewright@localhost",
    "GIT_COMMITTER_NAME": "Codewright",
    "GIT_COMMITTER_EMAIL": "codewright@localhost",
    "GIT_TERMINAL_PROMPT": "0",
}


def git(cwd: Path, *args: str, check: bool = True, timeout: float = 300) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, **GIT_ENV},
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()[:500]}")
    return result.stdout.strip()


@dataclass(frozen=True)
class Summary:
    files: int
    size_bytes: int
    languages: dict[str, int]  # language → number of files, most first
    top_level: list[str]


class Workspace:
    def __init__(self, root: Path, project_id: str) -> None:
        self.path = root / project_id
        self.source = self.path / "source"
        self.work = self.path / "work"

    def create(self) -> None:
        for name in LAYOUT:
            (self.path / name).mkdir(parents=True, exist_ok=True)

    def import_tree(self, tree: Path) -> None:
        """Copy an extracted/cloned tree into `source/` and `work/`. A cloned repo keeps its history in `work/`
        (so changes can become a pull request); anything else starts a new repo with one commit."""
        self.create()
        cloned = (tree / ".git").is_dir()
        for target in (self.source, self.work):
            shutil.rmtree(target, ignore_errors=True)
            keep_git = cloned and target == self.work
            ignore = None if keep_git else shutil.ignore_patterns(".git")
            shutil.copytree(tree, target, symlinks=False, ignore=ignore, dirs_exist_ok=False)
        if not cloned:
            self.init_git()

    def init_git(self) -> None:
        git(self.work, "init", "-q", "-b", "main")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "--allow-empty", "-m", "Imported by Codewright")

    def branch(self, name: str) -> None:
        """Create (or switch to) a change branch in `work/`."""
        existing = git(self.work, "branch", "--list", name)
        git(self.work, "checkout", "-q", *(() if existing else ("-b",)), name)

    def current_branch(self) -> str:
        return git(self.work, "rev-parse", "--abbrev-ref", "HEAD")

    def commit_all(self, message: str) -> bool:
        git(self.work, "add", "-A")
        if not git(self.work, "status", "--porcelain"):
            return False
        git(self.work, "commit", "-q", "-m", message)
        return True

    def summary(self) -> Summary:
        files, size = 0, 0
        langs: Counter[str] = Counter()
        base = self.work if self.work.exists() else self.source
        if not base.exists():
            return Summary(0, 0, {}, [])
        for path in base.rglob("*"):
            rel = path.relative_to(base).parts
            if any(p in SKIP_DIRS for p in rel) or not path.is_file():
                continue
            files += 1
            size += path.stat().st_size
            if lang := LANGUAGES.get(path.suffix.lower()):
                langs[lang] += 1
        top = sorted(p.name + ("/" if p.is_dir() else "") for p in base.iterdir() if p.name != ".git")[:30]
        return Summary(files, size, dict(langs.most_common()), top)

    def delete(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
