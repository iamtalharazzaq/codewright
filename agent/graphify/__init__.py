"""Graphify wrapper (CODEWRIGHT.md Section 8.2): build and query a project's code graph.

Graphify (`graphifyy` on PyPI) parses code locally with tree-sitter: no LLM is needed for code, so it runs with
`GRAPHIFY_BACKEND=none`. It writes `graphify-out/graph.json` inside the folder it reads (kept out of git) and caches
per file, so a rebuild after a few changed files takes seconds.

Versions live in `workspaces/<project>/graph/`: `latest.json` (the raw Graphify graph), `v<N>.json` (the module graph
of each version, small, for the timeline) and `versions.json` (the index).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.knowledge_graph import ModuleGraph, diff, enrich, hygiene, module_graph

ENV = {"GRAPHIFY_BACKEND": "none", "NO_COLOR": "1"}
OUT = "graphify-out"
TIMEOUT = 600
QUERY_CHARS = 4000  # what a prompt gets of a query answer


class GraphifyError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path, timeout: float = TIMEOUT) -> subprocess.CompletedProcess[str]:
    exe = shutil.which("graphify")
    if exe is None:
        raise GraphifyError("Graphify isn't installed (pip install graphifyy).")
    return subprocess.run(  # noqa: S603 - fixed executable, arguments are not shell-parsed
        [exe, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, **ENV},
        check=False,
    )


def _exclude_from_git(work: Path) -> None:
    exclude = work / ".git" / "info" / "exclude"
    if exclude.parent.is_dir():
        text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if f"{OUT}/" not in text.split():
            exclude.write_text(text.rstrip("\n") + f"\n{OUT}/\n", encoding="utf-8")


@dataclass(frozen=True)
class Version:
    number: int
    created_at: float
    reason: str
    nodes: int
    edges: int
    modules: int
    diff: dict[str, Any]
    hygiene: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class GraphStore:
    """The graph folder of one project."""

    def __init__(self, graph_dir: Path) -> None:
        self.dir = graph_dir

    @property
    def raw(self) -> Path:
        return self.dir / "latest.json"

    def versions(self) -> list[dict[str, Any]]:
        index = self.dir / "versions.json"
        if not index.exists():
            return []
        data: list[dict[str, Any]] = json.loads(index.read_text(encoding="utf-8"))
        return data

    def modules(self, number: int | None = None) -> ModuleGraph | None:
        versions = self.versions()
        if not versions:
            return None
        n = number if number is not None else versions[-1]["number"]
        path = self.dir / f"v{n}.json"
        if not path.exists():
            return None
        data: ModuleGraph = json.loads(path.read_text(encoding="utf-8"))
        return data

    def build(self, work: Path, reason: str = "build") -> Version:
        """Run Graphify on `work/`, then save a new version with its module graph, diff and hygiene report."""
        _exclude_from_git(work)
        result = _run(["update", ".", "--no-cluster", "--force"], cwd=work)
        out = work / OUT / "graph.json"
        if result.returncode != 0 or not out.exists():
            detail = (result.stderr or result.stdout).strip().splitlines()[-3:]
            raise GraphifyError("Graphify failed: " + " ".join(detail)[:500])
        raw: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
        modules = enrich(module_graph(raw), work)

        self.dir.mkdir(parents=True, exist_ok=True)
        versions = self.versions()
        previous = self.modules()
        number = versions[-1]["number"] + 1 if versions else 1
        version = Version(
            number=number,
            created_at=time.time(),
            reason=reason,
            nodes=len(raw.get("nodes", [])),
            edges=len(raw.get("links", [])),
            modules=len(modules["nodes"]),
            diff=diff(previous, modules),
            hygiene=hygiene(raw, modules, work),
        )
        shutil.copyfile(out, self.raw)
        unchanged = not any(version.diff.values()) if previous is not None else not modules["nodes"]
        if unchanged and versions:
            return Version(**versions[-1])  # nothing new to show on the timeline
        (self.dir / f"v{number}.json").write_text(json.dumps(modules), encoding="utf-8")
        versions.append(version.as_dict())
        (self.dir / "versions.json").write_text(json.dumps(versions), encoding="utf-8")
        return version

    # ── queries (Graphify CLI on the latest graph) ──────────────────────────
    def _ask(self, args: list[str]) -> str:
        if not self.raw.exists():
            raise GraphifyError("This project has no graph yet.")
        result = _run([*args, "--graph", str(self.raw)], cwd=self.dir, timeout=60)
        text = (result.stdout or result.stderr).strip()
        return text[:QUERY_CHARS]

    def query(self, question: str) -> str:
        return self._ask(["query", question])

    def path(self, a: str, b: str) -> str:
        return self._ask(["path", a, b])

    def explain(self, name: str) -> str:
        return self._ask(["explain", name])
