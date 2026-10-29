"""`steps.finish()` is the single choke point every playbook node uses to record a step's outcome. A step whose
own job is to verify something (tests, lint, a build) must be able to say it failed, not just leave a prose
summary that a human has to notice — see Bug 1 in PROGRESS.md."""

from __future__ import annotations

from typing import cast

from agent.playbooks import steps
from agent.playbooks.plan import plan_from
from agent.playbooks.state import RunState
from agent.tests.conftest import FakeServices


async def test_finish_marks_the_step_and_plan_item_done_by_default() -> None:
    services = FakeServices()
    plan = plan_from([("verify", "Run the tests", "qa_engineer")])
    state = cast(RunState, {"run_id": "r1"})
    update = await steps.finish(services, state, plan, "verify", "qa_engineer", "3 test(s) passed")
    assert update["steps"]["verify"]["status"] == "done"
    assert next(p for p in update["plan"] if p["id"] == "verify")["status"] == "done"
    assert ("step_completed", "verify", {"role": "qa_engineer", "summary": "3 test(s) passed", "ok": True}) in (
        services.events
    )


async def test_finish_with_ok_false_marks_the_step_and_plan_item_failed() -> None:
    services = FakeServices()
    plan = plan_from([("verify", "Run the tests", "qa_engineer")])
    state = cast(RunState, {"run_id": "r1"})
    update = await steps.finish(
        services, state, plan, "verify", "qa_engineer", "tests failing: collection failure", ok=False
    )
    assert update["steps"]["verify"]["status"] == "failed"
    assert next(p for p in update["plan"] if p["id"] == "verify")["status"] == "failed"
    assert (
        "step_completed",
        "verify",
        {"role": "qa_engineer", "summary": "tests failing: collection failure", "ok": False},
    ) in services.events
