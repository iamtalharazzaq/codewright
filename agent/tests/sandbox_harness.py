"""The shared real-sandbox test harness (retrofit, 2026-10-29): one throwaway workspace/session helper and one
`ProjectTools` implementation backed by the real sandbox runner, reused by every playbook's real-sandbox tests
instead of each test file rolling its own. No mocks below this line - `RealProject` actually runs `cmake`/`go
test`/`pytest`/`npm test`/etc. in the real sandbox container. Combine with `agent.tests.cassette.cassette_llm` for
the model side to get a fully real, still-fast-and-repeatable playbook test.

The `workspace` fixture itself lives in `agent/tests/conftest.py` (not here) so every test module gets it from
pytest's normal fixture discovery instead of importing a same-named symbol, which `ruff` reads as a shadowed
redefinition the moment a test function also calls its parameter `workspace`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from agent.language_packs import detect_project
from agent.language_packs.base import Step
from agent.language_packs.executor import run_action, run_step
from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import git

UID = 10001


def _workspaces() -> Path:
    return Path(os.environ.get("SANDBOX_TEST_WORKSPACES", "/app/workspaces"))


def _chown(path: Path) -> None:
    for p in [path, *path.rglob("*")]:
        os.chown(p, UID, UID, follow_symlinks=False)


async def _events(_: dict[str, Any]) -> None:
    return None


async def start_session(client: SandboxClient, ws: str, work: Path) -> str:
    root = work.parent
    subprocess.run(["git", "init", "-q", str(work)], check=True)  # noqa: S603, S607
    # A real project always arrives with its files already committed; match that so playbooks that diff against
    # HEAD (e.g. upgrade's own change detection) see the fixture as a tracked baseline, not all-untracked.
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "fixture baseline", check=False)
    _chown(root)
    return str((await client.create_session(ws, []))["id"])


class RealProject:
    """`agent.playbooks.services.ProjectTools`, backed by the real sandbox runner. Covers what the retrofit's
    playbook tests actually exercise (build/test/lint/run_step on real source); the graph/search/verify/facts side
    a playbook test doesn't need is stubbed out honestly (empty/not-available) rather than faked with canned data."""

    def __init__(self, client: SandboxClient, sid: str, work: Path) -> None:
        self._client = client
        self._sid = sid
        self._work = work
        self.saved_facts: list[dict[str, Any]] = []

    @property
    def work(self) -> Path:
        return self._work

    async def summary(self) -> dict[str, Any]:
        return {}

    async def fresh_graph(self) -> dict[str, Any] | None:
        return None

    def graph_versions(self) -> list[dict[str, Any]]:
        return []

    def explain(self, name: str) -> str:
        return f"Node: {name}"

    async def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """A plain keyword grep over the real checkout, ranked by how many query words a line's file contains -
        not the real semantic search, but real enough to find the right file in these small fixtures."""
        words = [w for w in query.lower().split() if len(w) > 2]
        hits: list[tuple[int, dict[str, Any]]] = []
        for path in self._work.rglob("*"):
            if not path.is_file() or ".git" in path.parts or ".codewright" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            score = sum(text.lower().count(w) for w in words)
            if score:
                rel = str(path.relative_to(self._work))
                hits.append((score, {"path": rel, "start_line": 1, "end_line": 1, "content": text.splitlines()[0]}))
        hits.sort(key=lambda sh: -sh[0])
        return [h for _, h in hits[:limit]]

    async def lint(self, paths: list[str] | None = None) -> list[dict[str, Any]]:
        return await self._run_steps("lint")

    async def sandbox(self, action: str, paths: list[str] | None = None) -> list[dict[str, Any]]:
        return await self._run_steps(action)

    async def test(self, paths: list[str] | None = None) -> list[dict[str, Any]]:
        return await self._run_action("test")

    async def _run_action(self, action: Any) -> list[dict[str, Any]]:
        """`test()`'s shape: one dict per component (production's `ApiProjectTools.test()` returns
        `activity.results`, each entry an `ActionResult.as_dict()` - `component_result`/`failure_text` read it)."""
        [component] = detect_project(self._work)
        result = await run_action(self._client, self._sid, self._work, component, action, _events)
        return [
            {
                "component": result.component,
                "pack": result.pack,
                "ok": result.ok,
                "report": result.report.as_dict() if result.report else None,
                "error": result.error,
            }
        ]

    async def _run_steps(self, action: Any) -> list[dict[str, Any]]:
        """`lint()`/`sandbox()`'s shape: one dict per step actually run (production's `ApiProjectTools.lint()` and
        `.sandbox()` both return `step_outputs(activity)` - `code_review`'s `parse_lint` and `security`'s
        `dependency_findings` both read `step`/`output` per entry, not the per-component shape above)."""
        [component] = detect_project(self._work)
        result = await run_action(self._client, self._sid, self._work, component, action, _events)
        return [
            {
                "component": result.component,
                "pack": result.pack,
                "step": s.step,
                "ok": s.ok,
                "exit_code": s.exit_code,
                "output": s.output_tail,
            }
            for s in result.steps
        ]

    async def run_step(self, step: Step) -> dict[str, Any]:
        command, _ = await run_step(self._client, self._sid, step, _events)
        return {"ok": command.ok, "exit_code": command.exit_code, "output": command.output_tail}

    async def db_trial(self, up_file: str, queries: list[str]) -> dict[str, Any]:
        return {"ok": None, "error": "db_trial is not available in the real-sandbox retrofit harness"}

    def recordings(self) -> list[dict[str, Any]]:
        return []

    async def verify(self, action: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"ok": None, "error": "verify is not available in the real-sandbox retrofit harness", "report": None}

    def files_changed(self, paths: list[str]) -> None:
        pass

    def facts(self) -> list[dict[str, Any]]:
        return []

    async def add_facts(self, facts: list[dict[str, Any]]) -> None:
        self.saved_facts.extend(facts)
