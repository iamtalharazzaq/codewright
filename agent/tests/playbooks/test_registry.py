from __future__ import annotations

import pytest

from agent.playbooks.gates import gate_applies
from agent.playbooks.registry import get_playbook, playbooks
from agent.playbooks.state import ArtifactRef, BudgetState, add_artifacts, add_budget, empty_budget


def test_registry_loads_every_playbook_with_its_tier() -> None:
    pbs = playbooks()
    assert {"sample", "architecture_change"} <= set(pbs)
    assert pbs["sample"].tier == 2
    assert pbs["architecture_change"].tier == 2  # from the intent in config/tiers.yaml


def test_unknown_playbook() -> None:
    with pytest.raises(LookupError, match="Unknown playbook"):
        get_playbook("nope")


def test_flow_and_initial_plan_follow_the_inputs() -> None:
    spec = get_playbook("architecture_change").spec
    audit = spec.flow({"mode": "audit"})
    conversion = spec.flow({"mode": "conversion"})
    assert "foundation" not in audit and "foundation" in conversion
    assert [item[0] for item in spec.initial_plan({"mode": "audit"})] == [n for n in audit if not n.startswith("gate")]


def test_standard_gates_by_tier() -> None:
    assert [gate_applies("plan", t) for t in range(4)] == [False, False, True, True]
    assert [gate_applies("result", t) for t in range(4)] == [False, True, True, True]
    assert all(gate_applies("custom", t) for t in range(4))


def test_budget_reducer_starts_from_an_empty_channel_and_sums() -> None:
    delta: BudgetState = {
        "run": {"llm_calls": 1, "tokens": 10},
        "steps": {"plan": {"llm_calls": 1, "tokens": 10}},
        "extensions": 0,
    }
    total = add_budget({}, delta)  # type: ignore[typeddict-item]  # LangGraph's initial value
    total = add_budget(total, delta)
    assert total["run"] == {"llm_calls": 2, "tokens": 20}
    assert total["steps"]["plan"] == {"llm_calls": 2, "tokens": 20}
    assert add_budget(empty_budget(), {**empty_budget(), "extensions": 1})["extensions"] == 1


def test_artifacts_reducer_replaces_by_path() -> None:
    old: list[ArtifactRef] = [
        {"kind": "plan", "title": "Outline", "path": "outline.md", "step": "plan"},
        {"kind": "report", "title": "Brief", "path": "brief.md", "step": "work"},
    ]
    new: list[ArtifactRef] = [{"kind": "plan", "title": "Outline v2", "path": "outline.md", "step": "plan"}]
    merged = add_artifacts(old, new)
    assert [(a["path"], a["title"]) for a in merged] == [("brief.md", "Brief"), ("outline.md", "Outline v2")]
