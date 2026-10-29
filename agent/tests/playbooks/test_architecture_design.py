"""Architecture change, Phase 15, as whole runs: design for any target, and clean modules / modular monolith for real
(branch, boundary rules, small tested moves, replay), with a fake sandbox and replay."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from agent.decomposition.engine import alternatives
from agent.tests.conftest import FakeProject, FakeServices
from agent.tests.decomposition.test_boundaries_moves import SHOP, sh
from agent.tests.decomposition.test_engine import edge, goshop_like, node
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tests.playbooks.test_code_playbooks import GREEN, RED, repo
from agent.tools.workspace import git

REPLAY_OK = {"ok": True, "error": None, "report": {"counts": {"regression": 0, "exchanges": 9}}}


def shop_graph() -> dict[str, Any]:
    """The module graph of the SHOP project in test_boundaries_moves."""
    nodes = [node(f"shop/{m}", files=3, ext="py") for m in ("order", "user", "util", "web")]
    nodes[0]["files"] = ["shop/order/__init__.py", "shop/order/service.py"]
    edges = [
        edge("shop/order", "shop/user", 3), edge("shop/order", "shop/util", 3),
        edge("shop/web", "shop/order", 4), edge("shop/web", "shop/util", 2),
    ]  # fmt: skip
    return {"nodes": nodes, "edges": edges}


async def run(
    tmp_path: Path,
    project: FakeProject,
    answer: Any = approve_all,
    *,
    services: FakeServices | None = None,
    **inputs: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    services = services or FakeServices(project=project)
    return await drive(
        compiled("architecture_change", services),
        cfg(),
        initial_state("architecture_change", tmp_path, **inputs),
        answer,
    )


async def test_microservices_audit_designs_a_shop_with_reasons_languages_events_and_sagas(tmp_path: Path) -> None:
    work = repo(tmp_path, {"main.go": "package main\n"})
    project = FakeProject(work, goshop_like(), test_results=[[GREEN]])
    state, prompts = await run(
        tmp_path, project, target="microservices", mode="audit", request="scale and team autonomy"
    )

    assert gates_of(prompts) == ["gate1", "gate2", "gate3", "gate4", "gate8"]
    design = state["to_be"]["design"]
    kinds = [g["kind"] for g in design["groups"]]
    assert kinds.count("frontend") == 1 and kinds.count("backend") >= 3
    assert design["violations"] == []
    platform = state["to_be"]["platform"]
    assert platform["sagas"] and platform["sagas"][0]["compensations"]  # the order workflow spans several services
    assert platform["events"] and platform["broker"] == "NATS"
    assert set(state["language_plan"]) == {g["name"] for g in design["groups"] if g["kind"] == "backend"}
    assert all(c["mode"] == "extract" for c in state["language_plan"].values())  # Go stays Go
    assert state["service_queue"] and set(state["service_queue"]) == set(state["language_plan"])
    # Cards show Markdown briefs; nothing in the project changed.
    assert [list(p["summary"]) for p in prompts] == [
        ["intake_brief"],
        ["as_is_brief"],
        ["to_be_brief"],
        ["language_brief"],
        ["report_brief"],
    ]
    assert "Why this shape" in prompts[2]["summary"]["to_be_brief"]
    assert git(work, "status", "--porcelain").strip() == ""
    assert any(a["path"].endswith("to_be.mmd") for a in state["artifacts"])
    assert state["done_summary"].endswith("Nothing in the project was changed.")
    assert project.verified == [] and project.tested == [None]  # only the tests ran, once


async def test_edits_typed_at_the_gate_are_applied_and_revalidated(tmp_path: Path) -> None:
    work = repo(tmp_path, {"main.go": "package main\n"})
    project = FakeProject(work, goshop_like(), test_results=[[GREEN]])
    first, _ = alternatives(goshop_like())
    backend = [g["name"] for g in first["groups"] if g["kind"] == "backend"]
    asked = {"done": False}

    def answer(prompt: dict[str, Any]) -> dict[str, Any]:
        if prompt["gate"] == "gate3" and not asked["done"]:
            asked["done"] = True
            return {"decision": "edit", "comment": f"merge {backend[0]} and {backend[1]}. Then dance."}
        return {"decision": "approve"}

    state, prompts = await run(tmp_path, project, answer, target="modular_monolith", mode="audit")
    assert gates_of(prompts).count("gate3") == 2
    design = state["to_be"]["design"]
    assert design["edited"] and sum(g["kind"] == "backend" for g in design["groups"]) == len(backend) - 1
    assert any(f"You merged {backend[1]} into {backend[0]}" in line for line in design["rules_applied"])


async def test_a_note_that_is_not_an_edit_is_answered_not_ignored(tmp_path: Path) -> None:
    work = repo(tmp_path, {"main.go": "package main\n"})
    project = FakeProject(work, goshop_like(), test_results=[[GREEN]])
    answers = iter([{"decision": "edit", "comment": "make it nicer"}])
    state, _ = await run(
        tmp_path,
        project,
        lambda p: next(answers, {"decision": "approve"}) if p["gate"] == "gate3" else {"decision": "approve"},
        target="modular_monolith",
    )
    assert "Write it like `move payment to order`" in state["to_be_brief"]


async def test_recommend_picks_the_simplest_target_that_fits_and_says_why_not_microservices(tmp_path: Path) -> None:
    work = repo(tmp_path, {"app.py": "x = 1\n"})
    graph = {
        "nodes": [node("app", files=4, ext="py"), node("lib", files=3, ext="py")],
        "edges": [edge("app", "lib", 2)],
    }
    project = FakeProject(work, graph, test_results=[[GREEN]])
    state, prompts = await run(tmp_path, project, target="recommend", mode="audit", request="the code is messy")
    assert state["to_be"]["target"] == "modules" and state["to_be"]["recommendation"]["target"] == "modules"
    assert "Recommended: Clean modules / layers" in prompts[2]["summary"]["to_be_brief"]
    assert "Microservices are not recommended" in prompts[2]["summary"]["to_be_brief"]
    assert gates_of(prompts) == ["gate1", "gate2", "gate3", "gate8"]  # no languages for an in-app target


async def test_the_model_only_names_groups_and_a_bad_name_is_ignored(tmp_path: Path) -> None:
    work = repo(tmp_path, {"main.go": "package main\n"})
    project = FakeProject(work, goshop_like(), test_results=[[GREEN]])
    first, _ = alternatives(goshop_like())
    other = [g["name"] for g in first["groups"] if g["kind"] == "backend"]
    names = {"groups": [{"group": 0, "name": "Checkout Flow!", "purpose": "Takes the order."}, {"group": 1, "name": other[0], "purpose": "dup"},  # noqa: E501
                        {"group": 99, "name": "ghost", "purpose": "x"}]}  # fmt: skip
    client, _ = llm_returning(names)
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, _ = await run(tmp_path, project, services=services, target="modular_monolith", mode="audit", use_llm=True)
    groups = state["to_be"]["design"]["groups"]
    backend = [g for g in groups if g["kind"] == "backend"]
    assert backend[0]["name"] == "checkout-flow" and backend[0]["purpose"] == "Takes the order."
    assert "ghost" not in {g["name"] for g in groups}
    assert len({g["name"] for g in groups}) == len(groups)  # names stay unique


async def test_layers_design_finds_outward_dependencies(tmp_path: Path) -> None:
    work = repo(tmp_path, {"a.py": "x = 1\n"})
    graph = {"nodes": [node("api", ext="py"), node("services", ext="py"), node("models", ext="py")],
             "edges": [edge("api", "services", 3), edge("models", "api", 1)]}  # fmt: skip
    project = FakeProject(work, graph, test_results=[[GREEN]])
    state, _ = await run(tmp_path, project, target="modules", mode="audit")
    design = state["to_be"]["design"]
    assert [(v["from"], v["to"]) for v in design["violations"]] == [("models", "api")]
    assert "Why this shape" in state["to_be_brief"]


async def test_modular_monolith_conversion_moves_files_in_tested_steps_and_ships_the_checker(tmp_path: Path) -> None:
    work = repo(tmp_path, SHOP)
    project = FakeProject(
        work, shop_graph(), test_results=[[GREEN]], recordings=[{"id": "rec1"}], verifications={"replay": [REPLAY_OK]}
    )
    state, prompts = await run(tmp_path, project, target="modular_monolith", mode="conversion")

    assert gates_of(prompts) == ["gate1", "gate2", "gate3", "approve_result", "gate8"]
    done = [o for o in state["outcomes"] if o["done"]]
    assert done, state["outcomes"]
    assert state["baseline"]["branch"].startswith("codewright/architecture-")
    assert git(work, "branch", "--show-current").strip() == state["baseline"]["branch"]
    log = git(work, "log", "--format=%s").splitlines()
    assert log[0] == "Architecture: boundary rules and checker" and sum(
        s.startswith("Architecture: Move") or s.startswith("Architecture: Expose") for s in log
    ) == len(done)
    assert (work / "architecture/boundaries.json").is_file() and (work / "architecture/README.md").is_file()
    assert state["verification"]["behavior"] == {"checked": True, "ok": True, "regressions": 0, "exchanges": 9}
    assert state["verification"]["new_violations"] == 0
    assert "identical behavior" in state["result_brief"] and "Boundary rules" in state["result_brief"]
    assert git(work, "status", "--porcelain").strip() == ""
    # The project's own checker passes, and the code still imports.
    check = sh([sys.executable, "architecture/check_boundaries.py"], work)
    assert check.returncode == 0, check.stdout
    imported = sh([sys.executable, "-c", "import shop.web.views, shop.order"], work)
    assert imported.returncode == 0, imported.stderr
    assert state["published"]["branch"] == state["baseline"]["branch"] and "Restructured" in state["done_summary"]


async def test_a_move_that_breaks_the_tests_is_undone_exactly(tmp_path: Path) -> None:
    work = repo(tmp_path, SHOP)
    before = {rel: (work / rel).read_text(encoding="utf-8") for rel in SHOP}
    project = FakeProject(work, shop_graph(), test_results=[[GREEN], [RED]])  # green baseline, then red forever
    state, _ = await run(tmp_path, project, target="modular_monolith", mode="conversion")
    assert state["outcomes"] and not any(o["done"] for o in state["outcomes"])
    assert any("undone: the tests failed" in o["note"] for o in state["outcomes"])
    assert {rel: (work / rel).read_text(encoding="utf-8") for rel in SHOP} == before
    assert not (work / "shop/web/slug.py").exists()
    assert "tests FAIL" in state["steps"]["verify"]["summary"]


async def test_no_file_is_moved_when_the_tests_were_not_green_to_begin_with(tmp_path: Path) -> None:
    work = repo(tmp_path, SHOP)
    project = FakeProject(work, shop_graph(), test_results=[[RED]])
    state, _ = await run(tmp_path, project, target="modular_monolith", mode="conversion")
    assert state["outcomes"] == []
    assert any("no file was moved" in n for n in state["restructure_notes"])
    assert (work / "architecture/boundaries.json").is_file()  # the rules still stand as a ratchet
    assert "Behavior not replayed" in state["result_brief"]


async def test_reworking_the_result_starts_again_from_the_baseline(tmp_path: Path) -> None:
    work = repo(tmp_path, SHOP)
    project = FakeProject(work, shop_graph(), test_results=[[GREEN]])
    answers = iter([{"decision": "reject", "comment": "too much"}])

    def answer(prompt: dict[str, Any]) -> dict[str, Any]:
        return next(answers, {"decision": "approve"}) if prompt["gate"] == "approve_result" else {"decision": "approve"}

    state, prompts = await run(tmp_path, project, answer, target="modular_monolith", mode="conversion")
    assert gates_of(prompts).count("approve_result") == 2
    assert not (work / "shop/util/slug.py").exists()  # moved once, not twice and not lost
    assert (work / "shop/web/slug.py").is_file() or any(not o["done"] for o in state["outcomes"])


async def test_recommend_cannot_be_converted_directly_but_every_target_can_be_designed(tmp_path: Path) -> None:
    """Phase 17: merge, serverless and event-driven are real conversions now (CONVERT_TARGETS); only `recommend`
    (pick a target, don't commit to one) still has to be resolved to a real target first."""
    from pydantic import ValidationError  # noqa: PLC0415

    from agent.playbooks.registry import get_playbook  # noqa: PLC0415

    inputs = get_playbook("architecture_change").spec.inputs
    try:
        inputs.model_validate({"target": "recommend", "mode": "conversion"})
    except ValidationError as exc:
        assert "conversion" in str(exc)
    else:
        raise AssertionError("recommend conversion should be refused")
    for target in ("serverless", "merge", "event_driven", "modules", "modular_monolith", "microservices"):
        inputs.model_validate({"target": target, "mode": "conversion"})  # does not raise
    assert (
        inputs.model_validate({"target": "serverless"}).model_dump()["mode"] == "audit"
    )  # but every target can be designed
