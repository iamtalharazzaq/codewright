"""The config files that later phases read stay consistent with CODEWRIGHT.md."""

from pathlib import Path
from typing import Any

import yaml

CONFIG = Path(__file__).resolve().parents[2] / "config"

# CODEWRIGHT.md Section 4: the 20 intents and their default tiers.
INTENT_TIERS = {
    "general_help": 0,
    "project_manage": 0,
    "explain_code": 0,
    "analyze_audit": 0,
    "write_docs": 1,
    "write_tests": 1,
    "fix_bug": 1,
    "security_review": 1,
    "refactor": 2,
    "improve_performance": 2,
    "upgrade": 2,
    "database_change": 2,
    "add_feature": 2,
    "frontend_modernize": 2,
    "devops_deploy": 2,
    "translate_language": 3,
    "change_architecture": 2,
    "new_app": 1,
    "write_code": 1,
    "review_code": 0,
}
# Intents whose tier grows with risk or size.
MAX_TIERS = {"security_review": 2, "change_architecture": 3, "new_app": 3, "review_code": 2}


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((CONFIG / name).read_text())
    return data


def test_tiers_cover_the_20_intents_with_the_spec_tiers() -> None:
    tiers = _load("tiers.yaml")
    assert set(tiers["tiers"]) == {0, 1, 2, 3}
    intents = tiers["intents"]
    assert {name: i["tier"] for name, i in intents.items()} == INTENT_TIERS
    assert {name: i["max_tier"] for name, i in intents.items() if "max_tier" in i} == MAX_TIERS
    assert all(i["max_tier"] > i["tier"] for i in intents.values() if "max_tier" in i)
    assert len({i["playbook"] for i in intents.values()}) == 20
    assert tiers["clarifier"] == {"max_questions_per_round": 5, "max_rounds": 2}


def test_budgets_and_noise_rules_load() -> None:
    budgets = _load("budgets.yaml")
    assert budgets["defaults"]["reflection"]["max_loops"] == 5
    noise = _load("noise_rules.default.yaml")
    assert noise["compare"]["body"] == "semantic_json"
