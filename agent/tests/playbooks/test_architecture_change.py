from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from agent.llm.client import LLMClient
from agent.llm.config import LLMProfile
from agent.tests.conftest import FakeServices

from .helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, started


async def test_audit_mode_runs_steps_1_to_5_then_report_and_delivery(services: FakeServices, tmp_path: Path) -> None:
    graph = compiled("architecture_change", services)
    state, prompts = await drive(
        graph, cfg(), initial_state("architecture_change", tmp_path, simulate=True, mode="audit"), approve_all
    )

    assert gates_of(prompts) == ["gate1", "gate2", "gate3", "gate4", "gate8"]
    assert started(services.events) == ["intake", "baseline", "as_is", "to_be", "languages", "audit_report", "deliver"]
    assert all(item["status"] == "done" for item in state["plan"])
    assert "foundation" not in state["steps"]
    assert (tmp_path / "stub" / "audit_report" / "STUB.md").exists()


async def test_conversion_mode_builds_each_service_with_its_own_gate5(services: FakeServices, tmp_path: Path) -> None:
    graph = compiled("architecture_change", services)
    state, prompts = await drive(
        graph,
        cfg(),
        initial_state(
            "architecture_change", tmp_path, simulate=True, mode="conversion", services=["notification", "payment"]
        ),
        approve_all,
    )

    assert gates_of(prompts) == [
        "gate1",
        "gate2",
        "gate3",
        "gate4",
        "gate5:notification",
        "gate5:payment",
        "gate6",
        "gate7",
        "gate8",
    ]
    assert set(state["service_results"]) == {"notification", "payment"}
    assert {"build_service:notification", "build_service:payment"} <= set(state["steps"])
    assert started(services.events)[-1] == "deliver"
    assert (tmp_path / "stub" / "build_service" / "payment.md").exists()


async def test_reject_and_edit_send_the_step_back_for_rework(services: FakeServices, tmp_path: Path) -> None:
    answers = iter(
        [
            {"decision": "reject", "comment": "Payment also calls Notification"},  # gate1
            {"decision": "approve"},  # gate1 again
            {"decision": "edit", "comment": "rename Catalog"},  # gate2
        ]
    )

    def answer(prompt: dict[str, Any]) -> dict[str, Any]:
        return next(answers, {"decision": "approve"})

    graph = compiled("architecture_change", services)
    state, prompts = await drive(
        graph, cfg(), initial_state("architecture_change", tmp_path, simulate=True, mode="audit"), answer
    )

    assert gates_of(prompts)[:4] == ["gate1", "gate1", "gate2", "gate2"]
    assert started(services.events)[:4] == ["intake", "intake", "baseline", "as_is"]
    assert started(services.events).count("as_is") == 2
    assert [a["decision"] for a in state["approvals"]][:3] == ["reject", "approve", "edit"]
    assert "Payment also calls Notification" in (tmp_path / "stub" / "intake" / "STUB.md").read_text()


async def test_gate5_reject_rebuilds_the_same_service(services: FakeServices, tmp_path: Path) -> None:
    def answer(prompt: dict[str, Any]) -> dict[str, Any]:
        if prompt.get("subject") == "notification" and not answer.rejected:  # type: ignore[attr-defined]
            answer.rejected = True  # type: ignore[attr-defined]
            return {"decision": "reject", "comment": "3 replay diffs"}
        return {"decision": "approve"}

    answer.rejected = False  # type: ignore[attr-defined]
    graph = compiled("architecture_change", services)
    _, prompts = await drive(
        graph,
        cfg(),
        initial_state("architecture_change", tmp_path, simulate=True, mode="conversion", services=["notification"]),
        answer,
    )
    assert gates_of(prompts)[4:6] == ["gate5:notification", "gate5:notification"]


async def test_events_are_emitted_per_step(services: FakeServices, tmp_path: Path) -> None:
    graph = compiled("architecture_change", services)
    await drive(graph, cfg(), initial_state("architecture_change", tmp_path, simulate=True, mode="audit"), approve_all)
    assert started(services.events)[:3] == ["intake", "baseline", "as_is"]


def _client(name: str, handler: Any) -> LLMClient:
    prof = LLMProfile(base_url=f"http://{name}.internal/v1", model="m", num_ctx=4096)
    return LLMClient(name, prof, transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


async def test_gpu_lost_pauses_and_switching_to_cpu_continues(tmp_path: Path) -> None:
    def gpu_down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=req)

    def cpu_ok(req: httpx.Request) -> httpx.Response:
        content = '{"summary": "Intake checks the stack.", "next_step": "baseline"}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})

    services = FakeServices({"remote_gpu": _client("remote_gpu", gpu_down), "local_cpu": _client("local_cpu", cpu_ok)})
    graph = compiled("architecture_change", services)

    def answer(prompt: dict[str, Any]) -> Any:
        if prompt["kind"] == "llm_unavailable":
            assert prompt["profile"] == "remote_gpu" and "switch_to_cpu" in prompt["options"]
            return "switch_to_cpu"
        return {"decision": "approve"}

    state, prompts = await drive(
        graph, cfg(), initial_state("architecture_change", tmp_path, simulate=True, mode="audit", use_llm=True), answer
    )
    assert prompts[0]["kind"] == "llm_unavailable"
    assert state["llm_profile"] == "local_cpu"
    assert state["goals"]["llm_summary"]["next_step"] == "baseline"
    assert ("llm_unavailable", "intake") in [(e, s) for (e, s, _) in services.events]
