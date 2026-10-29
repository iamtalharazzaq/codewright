"""The `serverless` and `event_driven` targets' real conversion step (Phase 17), called directly the way
`test_microservices_conversion.py` calls `ms.foundation`/`ms.build_one`: a hand-built `to_be` state, skipping
intake/baseline, so the step under test is exercised without the rest of the gate machinery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.playbooks.architecture_change import design
from agent.tests.conftest import FakeProject, FakeServices
from agent.tests.microservices.test_foundation_extract import SHOP
from agent.tests.playbooks.helpers import initial_state
from agent.tests.playbooks.test_code_playbooks import GREEN, RED, repo

STATELESS_DESIGN = {
    "groups": [
        {"name": "util", "kind": "backend", "modules": ["shop/util"], "tables": [], "calls": [], "called_by": ["payment"]},  # noqa: E501
        {"name": "payment", "kind": "backend", "modules": ["shop/payment"], "tables": ["payments"], "calls": ["util"], "called_by": []},  # noqa: E501
    ]
}  # fmt: skip
EVENT_DESIGN = {
    "groups": [
        {"name": "order", "kind": "backend", "modules": ["shop/order"], "tables": ["orders"], "calls": ["payment"], "called_by": []},  # noqa: E501
        {"name": "payment", "kind": "backend", "modules": ["shop/payment"], "tables": ["payments"], "calls": [], "called_by": ["order"]},  # noqa: E501
    ]
}  # fmt: skip
EVENT_PLATFORM = {"events": [{"event": "order.changed", "producer": "order", "consumers": ["payment"], "why": "x"}]}


def make(
    tmp_path: Path, target: str, design_: dict[str, Any], platform: dict[str, Any] | None = None, **results: Any
) -> tuple[FakeProject, FakeServices, dict[str, Any]]:
    work = repo(tmp_path, SHOP)
    project = FakeProject(work, test_results=results.pop("test_results", [[GREEN]]), **results)
    services = FakeServices(project=project)
    state: dict[str, Any] = {
        **initial_state("architecture_change", tmp_path, target=target, mode="conversion", use_llm=False),
        "to_be": {"target": target, "design": design_, "title": "x", "why": [], "platform": platform or {}},
        "baseline": {"tests_green": True, "base_sha": "HEAD"},
        "feedback": {},
    }
    return project, services, state


async def test_serverless_packages_a_stateless_group_for_real(tmp_path: Path) -> None:
    project, services, state = make(tmp_path, "serverless", STATELESS_DESIGN)
    update = await design.restructure(services, state)
    outcomes = update["outcomes"]
    assert outcomes == [
        {
            "title": "Package `util` as a serverless function",
            "kind": "serverless",
            "file": "services/util",
            "to": "a deploy manifest",
            "reason": "packaged",
            "done": True,
            "note": "",
        }
    ]
    work = project.work
    assert (work / "services/util/src/shop/util/money.py").is_file()
    assert (work / "services/util/src/util_service/handler.py").is_file()
    assert (work / "services/util/deploy/template.yaml").is_file()
    results = update["platform_detail"]["serverless_results"]["util"]
    assert results["status"] == "packaged" and "shop.util.money" in results["exposed"]
    assert "def cents" in (work / "shop/util/money.py").read_text(encoding="utf-8")  # the monolith is untouched


async def test_serverless_with_a_red_baseline_packages_nothing(tmp_path: Path) -> None:
    project, services, state = make(tmp_path, "serverless", STATELESS_DESIGN)
    state["baseline"] = {"tests_green": False}
    update = await design.restructure(services, state)
    assert update["outcomes"] == [] and "nothing was packaged" in update["restructure_notes"][0]
    assert not (project.work / "services/util").exists()


async def test_serverless_undoes_a_package_whose_tests_fail(tmp_path: Path) -> None:
    project, services, state = make(tmp_path, "serverless", STATELESS_DESIGN, test_results=[[RED]])
    update = await design.restructure(services, state)
    assert update["outcomes"][0]["done"] is False and "undone" in update["outcomes"][0]["note"]
    assert not (project.work / "services/util").exists()


async def test_event_driven_wires_the_bus_and_subscriber_for_real(tmp_path: Path) -> None:
    project, services, state = make(tmp_path, "event_driven", EVENT_DESIGN, EVENT_PLATFORM)
    update = await design.restructure(services, state)
    work = project.work
    assert update["outcomes"] == [
        {
            "title": "Wire the event bus and subscribers",
            "kind": "event_driven",
            "file": "libs/events",
            "to": "libs/events/bus.py",
            "reason": "1 event(s) from the design",
            "done": True,
            "note": "",
        }
    ]
    assert (work / "libs/events/bus.py").is_file()
    text = (work / "shop/payment/service.py").read_text(encoding="utf-8")
    assert "codewright:event-subscriber:order.changed" in text and "def charge" in text
    assert (work / "docs/architecture/EVENTS_REVIEW.md").is_file()
    info = update["platform_detail"]["event_driven"]
    assert info["subscribed"] == {"order.changed": ["charge", "refund"]}


async def test_event_driven_with_no_events_in_the_design_does_nothing(tmp_path: Path) -> None:
    project, services, state = make(tmp_path, "event_driven", EVENT_DESIGN, {"events": []})
    update = await design.restructure(services, state)
    assert update["outcomes"] == []
    assert not (project.work / "libs").exists()


async def test_event_driven_undoes_the_wiring_if_it_changes_behavior(tmp_path: Path) -> None:
    project, services, state = make(tmp_path, "event_driven", EVENT_DESIGN, EVENT_PLATFORM, test_results=[[RED]])
    update = await design.restructure(services, state)
    assert update["outcomes"][0]["done"] is False
    assert "codewright:event-subscriber" not in (project.work / "shop/payment/service.py").read_text(encoding="utf-8")
    assert not (project.work / "libs/events/bus.py").exists()
