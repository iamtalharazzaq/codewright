from __future__ import annotations

from pathlib import Path

from agent.llm.budgets import exceeded, limits_for_tier
from agent.playbooks.state import BudgetState, empty_budget


def test_defaults_and_tier_0_overrides() -> None:
    tier2 = limits_for_tier(2)
    tier0 = limits_for_tier(0)
    assert tier2["step_max_llm_calls"] == 20 and tier2["run_max_tokens"] == 1_000_000
    assert tier0["run_max_tokens"] == 60_000 and tier0["run_max_hours"] == 0.5
    assert tier0["step_max_llm_calls"] == tier2["step_max_llm_calls"]  # only per_run is overridden


def test_custom_file(tmp_path: Path) -> None:
    path = tmp_path / "budgets.yaml"
    path.write_text(
        "defaults:\n  per_step: {max_llm_calls: 3, max_tokens: 100}\n  per_run: {max_tokens: 1000, max_hours: 1}\n"
    )
    assert limits_for_tier(1, path) == {
        "step_max_tokens": 100,
        "step_max_llm_calls": 3,
        "run_max_tokens": 1000,
        "run_max_hours": 1.0,
    }


def _used(step_calls: int = 0, step_tokens: int = 0, run_tokens: int = 0, extensions: int = 0) -> BudgetState:
    return {
        "run": {"llm_calls": step_calls, "tokens": run_tokens},
        "steps": {"work": {"llm_calls": step_calls, "tokens": step_tokens}},
        "extensions": extensions,
    }


def test_exceeded_names_the_limit_and_continue_doubles_it() -> None:
    limits = limits_for_tier(2)
    assert exceeded(limits, empty_budget(), "work", started_at=0, now=60) is None
    assert "LLM calls in step work" in (exceeded(limits, _used(step_calls=20), "work", 0, now=60) or "")
    assert exceeded(limits, _used(step_calls=20, extensions=1), "work", 0, now=60) is None
    assert "tokens in this run" in (exceeded(limits, _used(run_tokens=1_000_000), "work", 0, now=60) or "")
    assert "hours for this run" in (exceeded(limits, empty_budget(), "work", 0, now=12 * 3600) or "")
    # Another step's usage doesn't count against this step.
    assert exceeded(limits, _used(step_calls=20), "plan", 0, now=60) is None
