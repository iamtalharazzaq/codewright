"""Architecture change, microservices foundation (CODEWRIGHT.md 5.18, Phase 16) end to end in the real sandbox
runner (`make check-sandbox`; skipped otherwise): the gateway/platform/CI foundation is really written, really
committed, and the monolith's real tests run after it (`ms.foundation`'s own undo-on-red path). Called directly
the same way `test_microservices_conversion.py`'s fake-mocked tests already call `ms.foundation` - a hand-built
`to_be`/`language_plan` state, skipping intake/design/gates. No model call happens anywhere in `foundation` (it
only writes templated files and runs real tests). Reuses the exact `DESIGN`/`PLATFORM`/`LANGS`/`SHOP` fixture
`test_foundation_extract.py`'s fake-sandbox tests already proved the static generation against, plus a real
`pyproject.toml` and test file so the generated foundation's "run the real tests" step has something to run.

The second test continues from the written foundation into `ms.build_one("payment")`: the `payment` group is really
extracted into `services/payment` (a full FastAPI template, scaffolded) behind an anti-corruption layer, and the
monolith's real tests run after it together with the generated ACL tests (`detect_project` sees one component: the
service's own template tests are not run by this step). A model is only called to fix a red attempt; the fixture's
extraction is green on the first try, so none is.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent.playbooks.architecture_change import microservices as ms
from agent.tests.microservices.test_foundation_extract import DESIGN, LANGS, PLATFORM, RULES, SHOP
from agent.tests.playbooks.helpers import initial_state
from agent.tests.sandbox_harness import RealProject, start_session
from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import git

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(os.environ.get("SANDBOX_TESTS") != "1", reason="needs the sandbox runner: make check-sandbox"),
]

PYPROJECT = (
    '[project]\nname = "shop"\nversion = "0.1.0"\n\n'
    '[build-system]\nrequires = ["hatchling>=1.27"]\nbuild-backend = "hatchling.build"\n\n'
    '[tool.hatch.build.targets.wheel]\npackages = ["shop"]\n\n'
    '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
)
FILES = {
    **SHOP,
    "pyproject.toml": PYPROJECT,
    "tests/test_shop.py": (
        "from shop.order.checkout import place\n\n\n"
        "def test_place() -> None:\n    assert place(10) == {'charged': 20, 'currency': 'USD'}\n"
    ),
}


class RealServices:
    """`RunServices` for this test: real events are dropped, the LLM is never called (`foundation` only writes
    templated files and runs real tests), every project id hands back the one real-sandbox workspace."""

    def __init__(self, project: RealProject) -> None:
        self._project = project

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, object] | None = None
    ) -> None:
        return None

    def llm(self, profile: str, *, run_id: str, step: str, role: str) -> object:
        raise NotImplementedError("foundation needs no model call")

    def chat_model(self, profile: str, *, run_id: str, step: str, role: str, **kwargs: object) -> object:
        raise NotImplementedError("foundation needs no model call")

    def project(self, project_id: str) -> RealProject:
        return self._project

    async def create_project(self, run_id: str, name: str) -> str:
        raise AssertionError("architecture_change should not need a new project in this test")


def _write(work: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8")


def _state(work: Path) -> dict[str, Any]:
    return {
        **initial_state("architecture_change", work, target="microservices", mode="conversion", use_llm=False),
        "to_be": {"target": "microservices", "design": DESIGN, "platform": PLATFORM},
        "language_plan": {n: {"language": lang, "mode": "extract", "current": lang} for n, lang in LANGS.items()},
        "baseline": {"tests_green": True, "recording": None},
        "ms_rules": RULES,
        "feedback": {},
    }


async def test_the_foundation_is_written_committed_and_the_real_monolith_tests_still_pass(
    workspace: tuple[SandboxClient, str, Path],
) -> None:
    client, ws, work = workspace
    _write(work, FILES)
    sid = await start_session(client, ws, work)
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(work)], check=True)  # noqa: S603, S607
    try:
        project = RealProject(client, sid, work)
        services = RealServices(project)
        state = _state(work)
        update = await ms.foundation(services, state)  # type: ignore[arg-type]

        assert update["foundation"]["ok"], update["foundation"]
        assert (work / "gateway/nginx.conf").is_file()
        assert (work / "platform/docker-compose.yml").is_file()
        assert (work / "docs/services/payment.md").is_file()
        assert git(work, "log", "-1", "--format=%s").startswith("Microservices: gateway")
        assert git(work, "status", "--porcelain").strip() == ""
        assert "no image was built" in update["foundation_brief"].lower()
        assert update["foundation"]["behavior"]["checked"] is False  # no baseline recording was given
    finally:
        await client.delete_session(sid)


async def test_a_python_service_is_really_extracted_and_the_real_tests_pass(
    workspace: tuple[SandboxClient, str, Path],
) -> None:
    client, ws, work = workspace
    _write(work, FILES)
    sid = await start_session(client, ws, work)
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(work)], check=True)  # noqa: S603, S607
    try:
        project = RealProject(client, sid, work)
        services = RealServices(project)
        state = _state(work)
        state.update(await ms.foundation(services, state))  # type: ignore[arg-type]
        assert state["foundation"]["ok"], state["foundation"]

        out = await ms.build_one(services, state, "payment")  # type: ignore[arg-type]

        assert out["status"] == "extracted", out
        assert (work / "codewright_acl.py").is_file() and (work / "services/payment").is_dir()
        assert git(work, "log", "-1", "--format=%s").startswith("Extract the payment service")
        assert git(work, "status", "--porcelain").strip() == ""
        results = await project.test(None)
        [root] = results  # detect_project sees one component: the monolith, now with the generated ACL tests too
        cases = {c["name"] for c in root["report"]["cases"]}
        assert (
            root["ok"]
            and "tests.test_shop::test_place" in cases
            and "tests.test_acl_payment::test_the_default_is_the_local_code" in cases
        ), cases
        assert all(r["ok"] for r in results), results
        assert "not deployed" in ms.service_brief(out)
    finally:
        await client.delete_session(sid)
