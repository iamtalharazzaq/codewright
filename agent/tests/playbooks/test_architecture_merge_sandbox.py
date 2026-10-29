"""Architecture change, target `merge` (CODEWRIGHT.md Section 5.18, Phase 17) end to end in the real sandbox
runner (`make check-sandbox`; skipped otherwise): a tiny real Python app has one module real-extracted (via the
same `agent.microservices.extract` code a real Phase 16 conversion uses) behind a shim, committed as "already
converted" baseline; the playbook's `merge` target then detects it from the working tree, restores the real code,
deletes the service copy, and real tests prove the monolith still works - no LLM call happens anywhere in this
playbook (`use_llm` defaults to False: merge is "detected from the working tree, not a design", CODEWRIGHT.md
5.18). Python only, `merge` only: `serverless`/`event_driven` and the other 4 languages are not retrofitted here -
see PROGRESS.md's Retrofit section for the scope call on Phase 17.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agent.decomposition import boundaries as b
from agent.microservices import extract as ex
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state
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
    "shop/util/__init__.py": "",
    "shop/util/money.py": "def cents(x: float) -> int:\n    return round(x * 100)\n",
    "shop/payment/__init__.py": "",
    "shop/payment/gateway.py": "from shop.util.money import cents\n\n\ndef fee(amount: float) -> int:\n    return cents(amount) // 100\n",  # noqa: E501
    "shop/payment/service.py": (
        "from shop.payment.gateway import fee\n\n\ndef charge(amount: float, currency: str = 'EUR') -> dict:\n"
        "    return {'charged': amount + fee(amount), 'currency': currency}\n"
    ),
    "shop/order/__init__.py": "",
    "shop/order/checkout.py": (
        "from shop.payment import service\n\n\ndef place(amount: float) -> dict:\n"
        "    return service.charge(amount, currency='USD')\n"
    ),
    "tests/test_shop.py": (
        "from shop.order.checkout import place\nfrom shop.payment.service import charge\n\n\n"
        "def test_place() -> None:\n    assert place(10) == {'charged': 20, 'currency': 'USD'}\n\n\n"
        "def test_charge() -> None:\n    assert charge(10)['currency'] == 'EUR'\n"
    ),
}
RULES = {"modules": {"payment": ["shop/payment"]}}


class RealServices:
    """`RunServices` for this test: real events are dropped, the LLM is never called (this playbook's `use_llm`
    defaults to False - merge is detected from the working tree, not designed), every project id hands back the
    one real-sandbox workspace."""

    def __init__(self, project: RealProject) -> None:
        self._project = project

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, object] | None = None
    ) -> None:
        return None

    def llm(self, profile: str, *, run_id: str, step: str, role: str) -> object:
        raise NotImplementedError("merge needs no model call: use_llm defaults to False for this playbook")

    def chat_model(self, profile: str, *, run_id: str, step: str, role: str, **kwargs: object) -> object:
        raise NotImplementedError("merge needs no model call: use_llm defaults to False for this playbook")

    def project(self, project_id: str) -> RealProject:
        return self._project

    async def create_project(self, run_id: str, name: str) -> str:
        raise AssertionError("architecture_change should not need a new project in this test")


def _write(work: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8")


async def test_a_real_extracted_service_is_merged_back_and_tests_still_pass(
    workspace: tuple[SandboxClient, str, Path],
) -> None:
    client, ws, work = workspace
    _write(work, SHOP)
    subprocess.run(["git", "init", "-q", str(work)], check=True)  # noqa: S603, S607
    # Simulate what a real Phase 16 conversion leaves behind: `payment` really extracted (the same mechanical code
    # a real conversion uses) *before* `start_session` chowns the workspace to the sandbox user - every file this
    # creates must exist first, or the sandbox container can't write its own `__pycache__`/build output under them.
    plan_x = ex.plan_extraction(work, RULES, "payment")
    assert not plan_x.blocked, plan_x.blocked
    ex.apply_extraction(work, plan_x, b.py_roots(work), "payment_service")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "simulate a Phase 16 conversion: payment already extracted")
    sid = await start_session(client, ws, work)
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(work)], check=True)  # noqa: S603, S607
    try:
        project = RealProject(client, sid, work)
        services = RealServices(project)
        state = initial_state("architecture_change", work.parent, target="merge", mode="conversion")
        final, prompts = await drive(compiled("architecture_change", services), cfg(), state, approve_all)  # type: ignore[arg-type]
        gates = gates_of(prompts)
        assert gates[:4] == ["gate1", "gate2", "gate3", "gate4"] and "approve_result" in gates and gates[-1] == "gate8"

        outcomes = final["outcomes"]
        assert outcomes and all(o["done"] for o in outcomes), outcomes
        assert not (work / "services/payment").exists()
        assert not (work / "tests/test_acl_payment.py").exists()
        assert not (work / "shop/payment/_local_service.py").exists()
        assert "def charge" in (work / "shop/payment/service.py").read_text(encoding="utf-8")
        assert not (work / "codewright_acl.py").exists()
        assert final["verification"]["tests_ok"] is True, final["verification"]
        assert git(work, "status", "--porcelain").strip() == ""
    finally:
        await client.delete_session(sid)
