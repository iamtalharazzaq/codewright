"""The config files that later phases read stay consistent with the README."""

from pathlib import Path
from typing import Any

import yaml

CONFIG = Path(__file__).resolve().parents[2] / "config"

# README Section 4: the 18 intents and their default tiers.
README_INTENT_TIERS = {
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
    "convert_microservices": 3,
    "new_app": 3,
}


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((CONFIG / name).read_text())
    return data


def test_tiers_cover_the_18_intents_with_the_readme_tiers() -> None:
    tiers = _load("tiers.yaml")
    assert set(tiers["tiers"]) == {0, 1, 2, 3}
    intents = tiers["intents"]
    assert {name: i["tier"] for name, i in intents.items()} == README_INTENT_TIERS
    assert all(i.get("max_tier", i["tier"]) >= i["tier"] for i in intents.values())
    assert len({i["playbook"] for i in intents.values()}) == 18


def test_budgets_and_noise_rules_load() -> None:
    budgets = _load("budgets.yaml")
    assert budgets["defaults"]["reflection"]["max_loops"] == 5
    noise = _load("noise_rules.default.yaml")
    assert noise["compare"]["body"] == "semantic_json"
