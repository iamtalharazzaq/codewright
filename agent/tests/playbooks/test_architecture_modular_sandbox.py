"""Architecture change, target `modular_monolith` (CODEWRIGHT.md 5.15, Phase 15) end to end in the real sandbox
runner (`make check-sandbox`; skipped otherwise): the one mechanical move the design's rules call for actually
happens on a real checkout - the moved file's every import is really rewritten (`agent.decomposition.moves`, the
same code a real Phase 15 run uses), real tests run after it, and a real commit lands. Called directly the way
`test_architecture_other_targets.py` calls `design.restructure` for `serverless`/`event_driven` (a hand-built
`to_be` state, skipping intake/baseline/gates): no model call happens anywhere in this playbook for this target
("no model rewrites a file here", `agent/decomposition/moves.py`). Python only, one move only - `moves`'s own
fake-mocked unit tests (`test_boundaries_moves.py`) already cover `expose` and TypeScript moves; this phase proves
the real toolchain runs a move for real, not the move logic itself.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agent.playbooks.architecture_change import design
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
SHOP = {
    "pyproject.toml": PYPROJECT,
    "shop/__init__.py": "",
    "shop/order/__init__.py": "",
    "shop/order/checkout.py": "def place(amount: float) -> float:\n    return amount\n",
    "shop/util/__init__.py": "",
    "shop/util/money.py": "def cents(x: float) -> int:\n    return round(x * 100)\n",
    "shop/payment/__init__.py": "",
    "shop/payment/service.py": (
        "from shop.util.money import cents\n\n\ndef charge(amount: float) -> int:\n    return cents(amount) // 100\n"
    ),
    "tests/test_shop.py": "from shop.payment.service import charge\n\n\ndef test_charge() -> None:\n    assert charge(10) == 10\n",  # noqa: E501
}
# `money.py` lives under `util/` but only `payment` imports it (no module imports its own copy) - the planner's
# exact shape for "only one other module uses this file", proven against this same shape of fixture by
# `test_boundaries_moves.py::test_planner_finds_the_file_only_one_module_uses_and_the_internal_import`.
DESIGN = {
    "groups": [
        {"name": "order", "kind": "backend", "modules": ["shop/order"], "calls": []},
        {"name": "util", "kind": "backend", "modules": ["shop/util"], "calls": []},
        {"name": "payment", "kind": "backend", "modules": ["shop/payment"], "calls": ["util"]},
    ]
}


class RealServices:
    """`RunServices` for this test: real events are dropped, the LLM is never called (no model rewrites a file in
    this target), every project id hands back the one real-sandbox workspace."""

    def __init__(self, project: RealProject) -> None:
        self._project = project

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, object] | None = None
    ) -> None:
        return None

    def llm(self, profile: str, *, run_id: str, step: str, role: str) -> object:
        raise NotImplementedError("modular_monolith moves need no model call")

    def chat_model(self, profile: str, *, run_id: str, step: str, role: str, **kwargs: object) -> object:
        raise NotImplementedError("modular_monolith moves need no model call")

    def project(self, project_id: str) -> RealProject:
        return self._project

    async def create_project(self, run_id: str, name: str) -> str:
        raise AssertionError("architecture_change should not need a new project in this test")


def _write(work: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8")


async def test_a_file_only_one_module_uses_is_really_moved_and_tests_still_pass(
    workspace: tuple[SandboxClient, str, Path],
) -> None:
    client, ws, work = workspace
    _write(work, SHOP)
    sid = await start_session(client, ws, work)
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(work)], check=True)  # noqa: S603, S607
    try:
        project = RealProject(client, sid, work)
        services = RealServices(project)
        state = {
            **initial_state("architecture_change", work, target="modular_monolith", mode="conversion", use_llm=False),
            "to_be": {
                "target": "modular_monolith",
                "design": DESIGN,
                "title": "Modular monolith",
                "why": ["Keep one deployable, enforce clean module boundaries"],
                "platform": {},
            },
            "baseline": {"tests_green": True, "base_sha": "HEAD"},
            "feedback": {},
        }
        update = await design.restructure(services, state)  # type: ignore[arg-type]

        outcomes = update["outcomes"]
        assert outcomes == [
            {
                "title": "Move `shop/util/money.py` into `shop/payment`",
                "kind": "move",
                "file": "shop/util/money.py",
                "to": "shop/payment",
                "reason": "only `payment` uses it",
                "done": True,
                "note": "",
            }
        ], outcomes
        assert not (work / "shop/util/money.py").exists()
        assert (work / "shop/payment/money.py").is_file()
        assert "from shop.payment.money import cents" in (work / "shop/payment/service.py").read_text(encoding="utf-8")
        log = git(work, "log", "--format=%s")
        assert "Architecture: Move" in log and "Architecture: boundary rules and checker" in log
        assert (work / "architecture/boundaries.json").is_file()
        assert git(work, "status", "--porcelain").strip() == ""
    finally:
        await client.delete_session(sid)
