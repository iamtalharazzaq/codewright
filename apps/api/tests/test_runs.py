from __future__ import annotations

import json
from typing import Any

from langgraph.types import Command

from .conftest import AppFactory, wait_for, waiting

FAST = {"stub_delay_s": 0, "simulate": True}


def ms(mode: str = "audit", **inputs: Any) -> dict[str, Any]:
    """Body for a stub architecture-change run (microservices target)."""
    return {"playbook": "architecture_change", "inputs": {"mode": mode, **FAST, **inputs}}


def _approve_until_done(client: Any, run_id: str) -> tuple[dict[str, Any], list[str]]:
    gates: list[str] = []
    for _ in range(30):
        run = wait_for(client, run_id, waiting)
        if run["status"] != "waiting":
            return run, gates
        pending = run["pending"]
        gates.append(pending["gate"] + (f":{pending['subject']}" if pending.get("subject") else ""))
        assert client.post(f"/api/runs/{run_id}/answer", json={"decision": "approve"}).status_code == 202
    raise AssertionError("run did not finish")


def test_audit_run_pauses_at_each_gate_and_completes(app_factory: AppFactory) -> None:
    with app_factory() as client:
        run_id = client.post("/api/runs", json=ms()).json()["id"]
        run, gates = _approve_until_done(client, run_id)
        detail = client.get(f"/api/runs/{run_id}").json()

    assert run["status"] == "completed"
    assert gates == ["gate1", "gate2", "gate3", "gate4", "gate8"]
    assert [a["gate"] for a in detail["approvals"]] == gates
    assert detail["usage"]["llm_calls"] == 0


def test_conversion_run_has_a_gate5_per_service(app_factory: AppFactory) -> None:
    with app_factory() as client:
        body = ms("conversion", services=["notification", "payment"])
        run_id = client.post("/api/runs", json=body).json()["id"]
        run, gates = _approve_until_done(client, run_id)
    assert run["status"] == "completed"
    assert gates[4:6] == ["gate5:notification", "gate5:payment"]


def test_answering_a_gate_resumes_only_its_own_interrupt(app_factory: AppFactory) -> None:
    """A parallel step (e.g. two services built at once) can leave more than one interrupt pending at once;
    resuming must target the one being answered (`Command(resume={id: answer})`), not apply the answer to every
    pending interrupt with a bare `Command(resume=answer)` -- that crashed a real Phase 16 run when a model-choice
    string reached a different, simultaneously-pending gate that expected a decision dict."""
    with app_factory() as client:
        run_id = client.post("/api/runs", json=ms()).json()["id"]
        run = wait_for(client, run_id, waiting)
        interrupt_id = run["pending"]["_interrupt_id"]
        assert interrupt_id

        manager = client.app.state.run_manager  # type: ignore[attr-defined]
        captured: dict[str, Any] = {}
        real_spawn = manager._spawn

        def spy(run_id: Any, playbook: Any, graph_input: Any) -> None:
            captured["graph_input"] = graph_input
            real_spawn(run_id, playbook, graph_input)

        manager._spawn = spy
        assert client.post(f"/api/runs/{run_id}/answer", json={"decision": "approve"}).status_code == 202

    resume = captured["graph_input"]
    assert isinstance(resume, Command)
    assert resume.resume == {interrupt_id: {"decision": "approve", "comment": "", "edits": {}}}


def test_reject_needs_a_comment_and_reworks_the_step(app_factory: AppFactory) -> None:
    with app_factory() as client:
        run_id = client.post("/api/runs", json=ms()).json()["id"]
        wait_for(client, run_id, waiting)
        assert client.post(f"/api/runs/{run_id}/answer", json={"decision": "reject"}).status_code == 422
        res = client.post(f"/api/runs/{run_id}/answer", json={"decision": "reject", "comment": "Wrong DB"})
        assert res.status_code == 202
        run = wait_for(client, run_id, lambda r: r["status"] == "waiting" and r["pending"]["gate"] == "gate1")
        assert run["pending"]["gate"] == "gate1"  # intake ran again and came back to Gate 1
        client.post(f"/api/runs/{run_id}/cancel")


def test_only_one_active_run_and_cancel(app_factory: AppFactory) -> None:
    with app_factory() as client:
        run_id = client.post("/api/runs", json=ms()).json()["id"]
        second = client.post("/api/runs", json=ms())
        assert second.status_code == 409
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "cancelled"
        assert client.post("/api/runs", json=ms()).status_code == 201


def test_answering_a_run_that_is_not_waiting_is_a_conflict(app_factory: AppFactory) -> None:
    with app_factory() as client:
        run_id = client.post("/api/runs", json=ms(stub_delay_s=5)).json()["id"]
        res = client.post(f"/api/runs/{run_id}/answer", json={"decision": "approve"})
        assert res.status_code == 409
        client.post(f"/api/runs/{run_id}/cancel")


def test_run_resumes_after_api_restart(app_factory: AppFactory) -> None:
    with app_factory() as client:
        run_id = client.post("/api/runs", json=ms(stub_delay_s=0.5)).json()["id"]
        wait_for(client, run_id, waiting)
        client.post(f"/api/runs/{run_id}/answer", json={"decision": "approve"})
        wait_for(client, run_id, lambda r: r["current_step"] == "baseline")
    # The app (and its run manager) stopped mid-step. A new process picks the run up from the checkpoint.
    with app_factory() as client:
        run = wait_for(client, run_id, lambda r: r["status"] == "waiting" and r["pending"]["gate"] == "gate2")
        events = [e["type"] for e in _events(client, run_id)]
    assert run["pending"]["gate"] == "gate2"
    assert "resumed_after_restart" in events


def test_model_server_down_pauses_and_asks_then_traces_the_failure(app_factory: AppFactory) -> None:
    with app_factory() as client:
        body = {**ms(use_llm=True), "llm_profile": "remote_gpu"}
        run_id = client.post("/api/runs", json=body).json()["id"]
        run = wait_for(client, run_id, waiting)
        assert run["pending"]["kind"] == "llm_unavailable"
        assert run["pending"]["options"] == ["retry", "switch_to_cpu"]

        assert client.post(f"/api/runs/{run_id}/answer", json={"choice": "switch_to_cpu"}).status_code == 202
        run = wait_for(client, run_id, lambda r: r["status"] == "waiting" and r["llm_profile"] == "local_cpu")
        assert run["pending"]["profile"] == "local_cpu"  # the CPU server is down too in this test
        assert run["pending"]["options"] == ["retry"]

        traces = client.get("/api/traces", params={"run_id": run_id}).json()
        assert len(traces) >= 2 and all(t["status"] == "error" for t in traces)
        assert {t["profile"] for t in traces} == {"remote_gpu", "local_cpu"}
        assert traces[0]["step"] == "intake" and traces[0]["role"] == "business_analyst"
        client.post(f"/api/runs/{run_id}/cancel")


def test_events_stream_over_sse(app_factory: AppFactory) -> None:
    with app_factory() as client:
        run_id = client.post("/api/runs", json=ms()).json()["id"]
        wait_for(client, run_id, waiting)
        events = _events(client, run_id)
        client.post(f"/api/runs/{run_id}/cancel")
    types = [e["type"] for e in events]
    assert types[:2] == ["llm_health", "run_status"]  # health check before every run (README 8.1)
    assert "step_started" in types and types[-1] == "waiting"
    ids = [e["id"] for e in events]
    assert ids == sorted(ids)


def test_live_stream_ends_when_the_run_ends(app_factory: AppFactory) -> None:
    with app_factory() as client:
        run_id = client.post("/api/runs", json=ms()).json()["id"]
        run, _ = _approve_until_done(client, run_id)
        # follow=true on a finished run: the backlog, then the stream closes by itself.
        events = _events(client, run_id, follow="true")
        resumed = _events(client, run_id, after=events[-3]["id"])
    assert run["status"] == "completed"
    assert events[-1]["type"] == "run_status" and events[-1]["data"]["status"] == "completed"
    assert [e["id"] for e in resumed] == [e["id"] for e in events[-2:]]


def _events(client: Any, run_id: str, **params: Any) -> list[dict[str, Any]]:
    """Read the run's SSE stream (by default only the past events) and return the event payloads."""
    events: list[dict[str, Any]] = []
    with client.stream("GET", f"/api/runs/{run_id}/events", params={"follow": "false", **params}) as res:
        assert res.headers["content-type"].startswith("text/event-stream")
        for line in res.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line.removeprefix("data:").strip()))
    return events


def test_playbooks_are_listed_with_steps_gates_and_input_schema(client: Any) -> None:
    playbooks = {p["name"]: p for p in client.get("/api/playbooks").json()}
    sample = playbooks["sample"]
    assert [s["id"] for s in sample["steps"]] == ["plan", "work"]
    assert [(g["id"], g["kind"]) for g in sample["gates"]] == [("approve_plan", "plan"), ("approve_result", "result")]
    assert "request" in sample["inputs_schema"]["properties"]
    assert client.get("/api/playbooks/architecture_change").json()["tier"] == 2
    assert client.get("/api/playbooks/nope").status_code == 404


def test_bad_requests_are_rejected_before_a_run_starts(app_factory: AppFactory) -> None:
    with app_factory() as client:
        assert client.post("/api/runs", json={"playbook": "nope"}).status_code == 404
        bad = client.post("/api/runs", json={"playbook": "sample", "inputs": {"request": "x"}})
        assert bad.status_code == 422  # min_length 3, validated by the playbook's input model
        assert client.post("/api/runs", json={"playbook": "sample", "tier": 7}).status_code == 422
        assert client.get("/api/runs").json() == []


def test_sample_run_detail_has_flow_plan_artifacts_and_budget(app_factory: AppFactory) -> None:
    with app_factory() as client:
        body = {"playbook": "sample", "inputs": {"use_llm": False, "stub_delay_s": 0}}
        run_id = client.post("/api/runs", json=body).json()["id"]
        run, gates = _approve_until_done(client, run_id)
        detail = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "completed"
    assert gates == ["approve_plan", "approve_result"]
    assert detail["flow"] == ["plan", "approve_plan", "work", "approve_result"]
    assert [p["status"] for p in detail["plan"]] == ["done", "done"]
    assert [a["path"] for a in detail["artifacts"]] == ["outline.md", "brief.md"]
    assert detail["steps"]["work"]["status"] == "done"
    assert detail["budget"]["run"] == {"llm_calls": 0, "tokens": 0}


def test_a_higher_tier_adds_gates_and_a_lower_one_is_ignored(app_factory: AppFactory) -> None:
    with app_factory() as client:
        body = {"playbook": "sample", "tier": 0, "inputs": {"use_llm": False, "stub_delay_s": 0}}
        run = client.post("/api/runs", json=body).json()
        client.post(f"/api/runs/{run['id']}/cancel")
    assert run["tier"] == 2  # a run can raise its playbook's tier, never lower it


def test_budget_choices_only_answer_a_budget_prompt(app_factory: AppFactory) -> None:
    with app_factory() as client:
        body = {"playbook": "sample", "inputs": {"use_llm": False, "stub_delay_s": 0}}
        run_id = client.post("/api/runs", json=body).json()["id"]
        wait_for(client, run_id, waiting)
        res = client.post(f"/api/runs/{run_id}/answer", json={"choice": "continue"})
        assert res.status_code == 409  # the open prompt is a gate
        client.post(f"/api/runs/{run_id}/cancel")


def test_architecture_change_needs_a_built_target_and_microservices_is_tier_3(app_factory: AppFactory) -> None:
    with app_factory() as client:
        later = {"playbook": "architecture_change", "inputs": {"target": "serverless", "mode": "conversion"}}
        assert client.post("/api/runs", json=later).status_code == 422  # serverless can be designed, not converted yet
        no_project = {"playbook": "architecture_change", "inputs": {"target": "modular_monolith"}}
        assert client.post("/api/runs", json=no_project).status_code == 422  # a real design needs a project
        run = client.post("/api/runs", json=ms()).json()
        client.post(f"/api/runs/{run['id']}/cancel")
    assert run["tier"] == 3 and run["inputs"]["target"] == "microservices"
