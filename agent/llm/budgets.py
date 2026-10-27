"""Run budgets (README Section 9.2): tokens and LLM calls per step, tokens and hours per run.

Limits are resolved once, when a run is created, and stored in its state, so a run keeps the limits it started with.
When a limit is hit the run pauses and asks the user to continue (every limit grows by its base value) or stop.
"""

from __future__ import annotations

import time
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from agent.playbooks.state import BudgetLimits, BudgetState

BUDGETS_FILE = Path(__file__).resolve().parents[2] / "config" / "budgets.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        out[key] = _deep_merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


@cache
def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def limits_for_tier(tier: int, path: Path = BUDGETS_FILE) -> BudgetLimits:
    data = _load(path)
    resolved = _deep_merge(data["defaults"], (data.get("tiers") or {}).get(tier, {}))
    return {
        "step_max_tokens": int(resolved["per_step"]["max_tokens"]),
        "step_max_llm_calls": int(resolved["per_step"]["max_llm_calls"]),
        "run_max_tokens": int(resolved["per_run"]["max_tokens"]),
        "run_max_hours": float(resolved["per_run"]["max_hours"]),
    }


def exceeded(
    limits: BudgetLimits, budget: BudgetState, step: str, started_at: float, now: float | None = None
) -> str | None:
    """Which limit the run has reached before the next LLM call in `step`, as a sentence; None if within budget."""
    factor = 1 + budget["extensions"]
    step_used = budget["steps"].get(step, {"llm_calls": 0, "tokens": 0})
    hours = ((now if now is not None else time.time()) - started_at) / 3600
    checks = [
        (step_used["tokens"], limits["step_max_tokens"] * factor, f"tokens in step {step}"),
        (step_used["llm_calls"], limits["step_max_llm_calls"] * factor, f"LLM calls in step {step}"),
        (budget["run"]["tokens"], limits["run_max_tokens"] * factor, "tokens in this run"),
        (hours, limits["run_max_hours"] * factor, "hours for this run"),
    ]
    for used, limit, what in checks:
        if used >= limit:
            return (
                f"Used {used:,.1f} of {limit:,.1f} {what}."
                if what.startswith("hours")
                else f"Used {used:,} of {limit:,} {what}."
            )
    return None
