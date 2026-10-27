"""The live plan checklist (README Section 2.2 "Plan checklist"): helpers nodes use to build and update it."""

from __future__ import annotations

from collections.abc import Iterable

from agent.playbooks.state import PlanItem, PlanStatus


def plan_from(items: Iterable[tuple[str, str, str]]) -> list[PlanItem]:
    """(id, title, role) triples → a fresh plan, everything pending."""
    return [{"id": i, "title": t, "role": r, "status": "pending"} for i, t, r in items]


def mark(plan: list[PlanItem], item_id: str, status: PlanStatus) -> list[PlanItem]:
    """A copy of the plan with one item's status changed (unknown ids leave the plan unchanged)."""
    return [{**item, "status": status} if item["id"] == item_id else item for item in plan]
