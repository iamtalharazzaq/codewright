"""End to end in the real sandbox runner (`make check-sandbox`; skipped otherwise): every template scaffolds, builds,
passes its tests and its linters; the C++ fixture builds, passes its tests and runs in an interactive terminal."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import pytest

from agent.language_packs import detect_project, pack
from agent.language_packs.base import ServiceSpec
from agent.language_packs.executor import run_action, run_spec, run_step
from agent.language_packs.templates import scaffold
from agent.tests.language_packs.golden import FIXTURES
from agent.tests.sandbox_harness import _events, start_session
from agent.tools.sandbox import SandboxClient

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(os.environ.get("SANDBOX_TESTS") != "1", reason="needs the sandbox runner: make check-sandbox"),
]
MIN_TESTS = {
    "cli-python": 3,
    "api-go": 3,
    "web-react-ts": 2,
    "web-react-js": 2,
    "cli-cpp": 3,
    "cli-go": 4,
    "api-fastapi": 3,
    "api-node": 3,
    "library-python": 3,
    "library-ts": 5,
    "library-go": 3,
    "library-cpp": 4,
    "site-nextjs-ts": 3,
    "site-nextjs-js": 3,
}
_session = start_session


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


async def test_cpp_conan_fixture_builds(workspace: tuple[SandboxClient, str, Path]) -> None:
    """Conan is installed in the sandbox image; vcpkg isn't yet, so only the Conan fixture gets a real build here."""
    client, ws, work = workspace
    shutil.copytree(FIXTURES / "cpp_cmake_conan", work, dirs_exist_ok=True)
    sid = await _session(client, ws, work)
    try:
        [component] = detect_project(work)
        result = await run_action(client, sid, work, component, "build", _events)
        assert result.ok, [(s.step, s.output_tail) for s in result.steps if not s.ok]
        assert [s.step for s in result.steps] == ["install", "configure", "build"]
    finally:
        await client.delete_session(sid)


async def test_cpp_conan_upgrade_bumps_and_rebuilds(workspace: tuple[SandboxClient, str, Path]) -> None:
    """Phase 19 Open item: a CMake package-manager upgrade path. Bumps the Conan fixture's pinned nlohmann_json
    (3.11.3, the version the build fixture above already proves builds) to the real newer release Conan Center
    actually serves (3.12.0, confirmed present via `conan search` while building this), then rebuilds for real to
    prove the new pin resolves and compiles — not just that the text rewrite happened."""
    client, ws, work = workspace
    shutil.copytree(FIXTURES / "cpp_cmake_conan", work, dirs_exist_ok=True)
    sid = await _session(client, ws, work)
    try:
        [component] = detect_project(work)
        assert component.details["package_manager"] == "conan"
        [upgrade] = pack("cpp").upgrade_steps(work, component, "nlohmann_json", "3.12.0")
        result, _ = await run_step(client, sid, upgrade, _events)
        assert result.ok, result.output_tail
        assert "nlohmann_json/3.12.0" in (work / "conanfile.txt").read_text(encoding="utf-8")

        build = await run_action(client, sid, work, component, "build", _events)
        assert build.ok, [(s.step, s.output_tail) for s in build.steps if not s.ok]
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
