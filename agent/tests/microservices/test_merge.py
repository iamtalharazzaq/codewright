"""Merging services back into the monolith (Phase 17): the mechanical reverse of an extraction, tested against a
real extraction's output (`agent.microservices.extract`, Phase 16), not a hand-built guess at its shape."""

from __future__ import annotations

import json
from pathlib import Path

from agent.decomposition import boundaries as b
from agent.microservices import extract as ex
from agent.microservices import foundation as fd
from agent.microservices import merge as mg
from agent.tests.microservices.test_foundation_extract import DESIGN, SHOP, project

# `util` is deliberately left out: like the real `to_be` design (its groups never list `shop/util`), this leaves
# `shop/util` unowned, so an extraction treats it as a shared helper instead of blocking on an unbuilt dependency.
RULES = {"modules": {"payment": ["shop/payment"], "order": ["shop/order"]}}


def extracted(tmp_path: Path, name: str = "payment") -> Path:
    """A monolith with `name` genuinely extracted behind a shim and a gateway route, so the fixture is exactly what
    a Phase 16 conversion produces, not a guess at its shape."""
    work = project(tmp_path, SHOP)
    plan_x = ex.plan_extraction(work, RULES, name)
    assert not plan_x.blocked, plan_x.blocked
    roots = b.py_roots(work)
    ex.apply_extraction(work, plan_x, roots, f"{fd.safe_name(name)}_service")
    routes = fd.routes_for(DESIGN, {name: False})
    (work / "gateway").mkdir()
    (work / "gateway/routes.json").write_text(json.dumps(routes, indent=2) + "\n", encoding="utf-8")
    (work / "gateway/nginx.conf").write_text(fd.render_nginx(routes), encoding="utf-8")
    return work


def test_detect_finds_the_service_from_the_shim_it_generated(tmp_path: Path) -> None:
    work = extracted(tmp_path)
    found = mg.detect(work)
    assert found == {"payment": ["shop/payment/service.py"]}


def test_plan_merges_every_detected_service_by_default(tmp_path: Path) -> None:
    work = extracted(tmp_path)
    moves, notes = mg.plan(work)
    assert [m.service for m in moves] == ["payment"] and notes == []
    assert moves[0].service_dir == "services/payment"


def test_plan_notes_a_service_name_that_is_not_in_the_working_tree(tmp_path: Path) -> None:
    work = extracted(tmp_path)
    moves, notes = mg.plan(work, ["ghost"])
    assert moves == [] and "not found in the working tree" in notes[0]


def test_apply_merge_restores_the_local_code_and_deletes_the_service_copy(tmp_path: Path) -> None:
    work = extracted(tmp_path)
    before_shim = (work / "shop/payment/service.py").read_text(encoding="utf-8")
    before_local = (work / "shop/payment/_local_service.py").read_text(encoding="utf-8")
    moves, _ = mg.plan(work)
    before = mg.apply_merge(work, moves[0])
    assert (work / "shop/payment/service.py").read_text(encoding="utf-8") == before_local
    assert not (work / "shop/payment/_local_service.py").exists()
    assert not (work / "services/payment").exists()
    mg.restore(work, before)
    assert (work / "shop/payment/service.py").read_text(encoding="utf-8") == before_shim
    assert (work / "shop/payment/_local_service.py").is_file()
    assert (work / "services/payment").is_dir()


def test_merging_an_already_finalized_service_is_refused(tmp_path: Path) -> None:
    work = extracted(tmp_path)
    roots = b.py_roots(work)
    plan_x = ex.plan_extraction(work, RULES, "payment")
    ex.remove_local(work, plan_x, roots)  # the cut-over to 100%: the local copy is gone
    moves, _ = mg.plan(work)
    try:
        mg.apply_merge(work, moves[0])
    except mg.CannotMerge as exc:
        assert "finalized" in str(exc)
    else:
        raise AssertionError("merging a finalized service should be refused")


def test_drop_gateway_route_removes_the_entry_and_regenerates_nginx(tmp_path: Path) -> None:
    work = extracted(tmp_path)
    changed = mg.drop_gateway_route(work, "payment")
    routes = json.loads((work / "gateway/routes.json").read_text(encoding="utf-8"))
    assert "payment" not in routes["services"]
    assert "location /payment/" not in (work / "gateway/nginx.conf").read_text(encoding="utf-8")
    assert set(changed) == {"gateway/routes.json", "gateway/nginx.conf"}


def test_remove_unused_acl_only_once_every_shim_is_gone(tmp_path: Path) -> None:
    work = extracted(tmp_path)
    assert mg.acl_still_used(work) is True
    assert mg.remove_unused_acl(work) == []  # the shim is still there
    moves, _ = mg.plan(work)
    mg.apply_merge(work, moves[0])
    assert mg.acl_still_used(work) is False
    removed = mg.remove_unused_acl(work)
    assert removed == ["codewright_acl.py"] and not (work / "codewright_acl.py").exists()
