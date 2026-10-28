"""End to end in the real sandbox runner (`make check-sandbox`; skipped otherwise): every template scaffolds, builds,
passes its tests and its linters; the C++ fixture builds, passes its tests and runs in an interactive terminal."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from agent.language_packs import detect_project
from agent.language_packs.base import ServiceSpec
from agent.language_packs.executor import run_action, run_spec, run_step
from agent.language_packs.templates import scaffold
from agent.tests.language_packs.golden import FIXTURES
from agent.tools.sandbox import SandboxClient

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(os.environ.get("SANDBOX_TESTS") != "1", reason="needs the sandbox runner: make check-sandbox"),
]
UID = 10001
MIN_TESTS = {"cli-python": 3, "api-go": 3, "web-react-ts": 2, "web-react-js": 2, "cli-cpp": 3}


def _workspaces() -> Path:
    return Path(os.environ.get("SANDBOX_TEST_WORKSPACES", "/app/workspaces"))


def _chown(path: Path) -> None:
    for p in [path, *path.rglob("*")]:
        os.chown(p, UID, UID, follow_symlinks=False)


async def _events(_: dict[str, Any]) -> None:
    return None


@pytest.fixture
async def workspace() -> AsyncIterator[tuple[SandboxClient, str, Path]]:
    """A throwaway workspace in the real workspaces volume (the runner mounts `<id>/work` from there)."""
    ws = f"sbxtest-{uuid.uuid4().hex[:8]}"
    work = _workspaces() / ws / "work"
    work.mkdir(parents=True)
    client = SandboxClient()
    try:
        yield client, ws, work
    finally:
        await client.close()
        shutil.rmtree(work.parent, ignore_errors=True)


async def _session(client: SandboxClient, ws: str, work: Path) -> str:
    root = work.parent
    subprocess.run(["git", "init", "-q", str(work)], check=True)  # noqa: S603, S607
    _chown(root)
    return str((await client.create_session(ws, []))["id"])


@pytest.mark.parametrize("template", sorted(MIN_TESTS))
async def test_template_builds_tests_and_lints(template: str, workspace: tuple[SandboxClient, str, Path]) -> None:
    client, ws, work = workspace
    work.rmdir()
    scaffold(ServiceSpec("demo app", template, "A demo", 8080), work)
    sid = await _session(client, ws, work)
    try:
        [component] = detect_project(work)
        result = await run_action(client, sid, work, component, "test", _events)
        assert result.ok, result.as_dict()
        assert result.report and result.report.passed >= MIN_TESTS[template], result.report
        lint = await run_action(client, sid, work, component, "lint", _events)
        assert lint.ok, [(s.step, s.output_tail) for s in lint.steps if not s.ok]
    finally:
        await client.delete_session(sid)


async def test_cpp_fixture_runs_in_the_terminal(workspace: tuple[SandboxClient, str, Path]) -> None:
    client, ws, work = workspace
    shutil.copytree(FIXTURES / "cpp_cmake", work, dirs_exist_ok=True)
    sid = await _session(client, ws, work)
    try:
        [component] = detect_project(work)
        result = await run_action(client, sid, work, component, "test", _events)
        assert result.ok and result.report and result.report.passed == 2, result.as_dict()

        spec = run_spec(work, component)
        assert spec and spec.kind == "terminal"
        for step in spec.prepare:
            assert (await run_step(client, sid, step, _events))[0].ok
        preview = await client.start_preview(
            sid, {"kind": "terminal", "toolchain": "cpp", "cmd": spec.cmd, "workdir": spec.workdir}
        )
        output = bytearray()

        async def read_until(text: str) -> None:
            async def go() -> None:
                async for chunk in client.preview_output(sid, preview["id"]):
                    output.extend(chunk)
                    if text.encode() in output:
                        return

            output.clear()
            await asyncio.wait_for(go(), 20)

        await read_until("> ")
        await client.send_input(sid, preview["id"], "5\r")
        await client.send_input(sid, preview["id"], "7\r")
        await read_until("total = 12")
        await client.send_input(sid, preview["id"], "quit\r")
        await read_until("bye, total 12")
        for _ in range(20):
            info = await client.preview(sid, preview["id"])
            if not info["running"]:
                break
            await asyncio.sleep(0.25)
        assert info["exit_code"] == 0
    finally:
        await client.delete_session(sid)
