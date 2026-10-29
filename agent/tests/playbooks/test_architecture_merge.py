"""Acceptance (CODEWRIGHT.md 5.18 / Phase 17): a small multi-service fixture merged back into one app with 0
regressions, driven through the whole `architecture_change` graph (gates, baseline, verify, report), with a fake
sandbox and a fake replay — the acceptance criterion the ADR calls out as locally verifiable without the API."""

from __future__ import annotations

import json
from pathlib import Path

from agent.decomposition import boundaries as b
from agent.microservices import extract as ex
from agent.microservices import foundation as fd
from agent.tests.conftest import FakeProject
from agent.tests.decomposition.test_engine import goshop_like
from agent.tests.microservices.test_foundation_extract import DESIGN, SHOP
from agent.tests.playbooks.helpers import gates_of
from agent.tests.playbooks.test_architecture_design import REPLAY_OK, run
from agent.tests.playbooks.test_code_playbooks import GREEN, repo
from agent.tools.workspace import git

# The module graph only drives the `to_be`/`languages` steps' cards; the actual merge is detected straight from the
# working tree (the shim), so a proven fixture graph (`goshop_like`) stands in without needing to match the files.
# `util` is left out of the extraction rules, same as the real `to_be` design's groups: unowned, it is copied as a
# shared helper rather than blocking the extraction on an unbuilt dependency.
RULES = {"modules": {"payment": ["shop/payment"], "order": ["shop/order"]}}


def fixture(tmp_path: Path) -> Path:
    """A git repo with `payment` already extracted behind a shim and routed at the gateway: exactly what a Phase 16
    microservices conversion leaves behind, committed so the playbook's own baseline branch has something to work
    from."""
    work = repo(tmp_path, SHOP)
    plan_x = ex.plan_extraction(work, RULES, "payment")
    assert not plan_x.blocked, plan_x.blocked
    roots = b.py_roots(work)
    ex.apply_extraction(work, plan_x, roots, "payment_service")
    routes = fd.routes_for(DESIGN, {"payment": False})
    (work / "gateway").mkdir()
    (work / "gateway/routes.json").write_text(json.dumps(routes, indent=2) + "\n", encoding="utf-8")
    (work / "gateway/nginx.conf").write_text(fd.render_nginx(routes), encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "simulate a Phase 16 conversion: payment already extracted")
    return work


async def test_a_small_multi_service_fixture_is_merged_back_with_0_regressions(tmp_path: Path) -> None:
    work = fixture(tmp_path)
    project = FakeProject(
        work, goshop_like(), test_results=[[GREEN]], recordings=[{"id": "rec1"}], verifications={"replay": [REPLAY_OK]}
    )  # fmt: skip
    state, prompts = await run(tmp_path, project, target="merge", mode="conversion")

    gates = gates_of(prompts)
    assert gates[:4] == ["gate1", "gate2", "gate3", "gate4"] and gates[-1] == "gate8" and "approve_result" in gates
    done = [o for o in state["outcomes"] if o["done"]]
    assert done and done[0]["title"] == "Merge `payment` back into the monolith"
    assert not any(not o["done"] for o in state["outcomes"]), state["outcomes"]

    # The service is gone; the monolith calls its own code again, directly, with no shim left.
    assert not (work / "services/payment").exists()
    assert not (work / "shop/payment/_local_service.py").exists()
    service_text = (work / "shop/payment/service.py").read_text(encoding="utf-8")
    assert "def charge" in service_text and "codewright:shim" not in service_text
    assert not (work / "codewright_acl.py").exists()  # the anti-corruption layer is dead code once nothing calls it

    # The gateway no longer routes to a service that doesn't exist.
    routes = json.loads((work / "gateway/routes.json").read_text(encoding="utf-8"))
    assert "payment" not in routes["services"]
    assert "location /payment/" not in (work / "gateway/nginx.conf").read_text(encoding="utf-8")

    # 0 regressions, proven the same way every other target proves it: the replay, not a claim.
    assert state["verification"]["behavior"] == {"checked": True, "ok": True, "regressions": 0, "exchanges": 9}
    assert state["verification"]["tests_ok"] is True

    # The working tree is clean (every change was committed) and the before/after report was written.
    assert git(work, "status", "--porcelain").strip() == ""
    assert any(a["path"].endswith("COMPARISON.md") for a in state["artifacts"])
    assert (work / "docs/architecture/COMPARISON.md").is_file()
    assert "merged" in state["report_brief"].lower() or "Merge" in state["report_brief"]
