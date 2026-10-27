"""The sample playbook: the run pattern (plan → gate → agent team → gate) with tiers, budgets and GPU loss."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import openai
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult

from agent.llm.client import LLMClient
from agent.llm.config import LLMProfile
from agent.playbooks.llm_step import RunStopped
from agent.tests.conftest import FakeServices
from agent.tests.test_team import ScriptedModel, call

from .helpers import approve_all, cfg, compiled, drive, gates_of, initial_state

OUTLINE = {"title": "Clinic booking", "sections": ["Problem", "Users", "Scope"]}


def outline_client() -> LLMClient:
    def handler(req: httpx.Request) -> httpx.Response:
        content = json.dumps(OUTLINE)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            },
        )

    prof = LLMProfile(base_url="http://gpu.internal/v1", model="m", num_ctx=4096)
    return LLMClient("remote_gpu", prof, transport=httpx.MockTransport(handler))


def team_script() -> ScriptedModel:
    """Project Manager delegates, Business Analyst writes brief.md, both finish."""
    return ScriptedModel(
        messages=iter(
            [
                call("task", {"description": "Write /brief.md", "subagent_type": "business-analyst"}, "c1"),
                call("write_file", {"file_path": "/brief.md", "content": "# Clinic booking\n\n## Problem\n"}, "c2"),
                AIMessage(content="Wrote /brief.md."),
                AIMessage(content="Done."),
            ]
        )
    )


class DownModel(GenericFakeChatModel):
    """The GPU is gone: every call fails like the OpenAI SDK does when the server can't be reached."""

    async def _agenerate(self, *args: Any, **kwargs: Any) -> ChatResult:
        request = httpx.Request("POST", "http://gpu.internal/v1/chat/completions")
        raise openai.APIConnectionError(request=request)  # type: ignore[arg-type]  # openai types its own httpx

    def bind_tools(self, tools: Any, **kwargs: Any) -> DownModel:
        return self


async def test_tier_2_asks_for_plan_and_result_and_writes_the_files(services: FakeServices, tmp_path: Path) -> None:
    state, prompts = await drive(
        compiled("sample", services), cfg(), initial_state("sample", tmp_path, use_llm=False), approve_all
    )
    assert gates_of(prompts) == ["approve_plan", "approve_result"]
    assert prompts[0]["playbook"] == "sample" and prompts[0]["tier"] == 2
    assert [p["status"] for p in state["plan"]] == ["done", "done"]
    assert [a["path"] for a in state["artifacts"]] == ["outline.md", "brief.md"]
    assert (tmp_path / "brief.md").read_text().startswith("# Project brief")


async def test_lower_tiers_skip_gates(services: FakeServices, tmp_path: Path) -> None:
    _, tier1 = await drive(
        compiled("sample", services), cfg("t1"), initial_state("sample", tmp_path, tier=1, use_llm=False), approve_all
    )
    _, tier0 = await drive(
        compiled("sample", services), cfg("t0"), initial_state("sample", tmp_path, tier=0, use_llm=False), approve_all
    )
    assert gates_of(tier1) == ["approve_result"]
    assert gates_of(tier0) == []


async def test_edit_reruns_the_plan_and_replaces_its_artifact(services: FakeServices, tmp_path: Path) -> None:
    answers = iter([{"decision": "edit", "comment": "Add a pricing section"}])

    def answer(prompt: dict[str, Any]) -> dict[str, Any]:
        return next(answers, {"decision": "approve"})

    state, prompts = await drive(
        compiled("sample", services), cfg(), initial_state("sample", tmp_path, use_llm=False), answer
    )
    assert gates_of(prompts) == ["approve_plan", "approve_plan", "approve_result"]
    assert state["feedback"]["plan"] == "Add a pricing section"
    assert [a["path"] for a in state["artifacts"]] == ["outline.md", "brief.md"]  # no duplicate after the rework


async def test_with_the_model_the_team_writes_the_brief_and_usage_is_counted(tmp_path: Path) -> None:
    services = FakeServices({"remote_gpu": outline_client()}, {"remote_gpu": team_script()})
    state, _ = await drive(compiled("sample", services), cfg(), initial_state("sample", tmp_path), approve_all)

    assert state["outline"] == OUTLINE
    assert (tmp_path / "outline.md").read_text().startswith("# Clinic booking")
    assert (tmp_path / "brief.md").read_text().startswith("# Clinic booking")
    assert state["steps"]["work"]["status"] == "done"
    budget = state["budget"]
    assert budget["steps"]["plan"] == {"llm_calls": 1, "tokens": 70}
    assert budget["steps"]["work"]["llm_calls"] == 4  # PM, BA, BA, PM
    assert budget["run"]["llm_calls"] == 5


async def test_gpu_lost_inside_the_agent_team_pauses_and_retry_continues(tmp_path: Path) -> None:
    services = FakeServices({"remote_gpu": outline_client()}, {"remote_gpu": DownModel(messages=iter([]))})
    graph = compiled("sample", services)

    def answer(prompt: dict[str, Any]) -> Any:
        if prompt["kind"] == "llm_unavailable":
            services.chat_models["remote_gpu"] = team_script()  # the server is back
            return "retry"
        return {"decision": "approve"}

    _, prompts = await drive(graph, cfg(), initial_state("sample", tmp_path), answer)
    kinds = [(p["kind"], p.get("step") or p.get("gate")) for p in prompts]
    assert kinds == [("gate", "approve_plan"), ("llm_unavailable", "work"), ("gate", "approve_result")]
    assert prompts[1]["options"] == ["retry", "switch_to_cpu"]
    assert (tmp_path / "brief.md").exists()
    assert ("llm_unavailable", "work") in [(e, s) for (e, s, _) in services.events]


def _over_budget(tmp_path: Path) -> dict[str, Any]:
    state: dict[str, Any] = dict(initial_state("sample", tmp_path))
    state["limits"] = {**state["limits"], "step_max_llm_calls": 1}
    state["budget"] = {
        "run": {"llm_calls": 1, "tokens": 0},
        "steps": {"work": {"llm_calls": 1, "tokens": 0}},
        "extensions": 0,
    }
    return state


async def test_budget_reached_asks_and_continue_extends_it(tmp_path: Path) -> None:
    services = FakeServices({"remote_gpu": outline_client()}, {"remote_gpu": team_script()})
    state, prompts = await drive(
        compiled("sample", services), cfg(), _over_budget(tmp_path), approve_all_or("continue")
    )
    budget_prompt = next(p for p in prompts if p["kind"] == "budget_exceeded")
    assert budget_prompt["step"] == "work" and budget_prompt["options"] == ["continue", "stop"]
    assert state["budget"]["extensions"] == 1
    assert (tmp_path / "brief.md").exists()


async def test_budget_reached_and_stop_ends_the_run(tmp_path: Path) -> None:
    services = FakeServices({"remote_gpu": outline_client()}, {"remote_gpu": team_script()})
    try:
        await drive(compiled("sample", services), cfg(), _over_budget(tmp_path), approve_all_or("stop"))
    except RunStopped as exc:
        assert "work" in str(exc)
    else:
        raise AssertionError("expected RunStopped")
    assert not (tmp_path / "brief.md").exists()


def approve_all_or(choice: str) -> Any:
    def answer(prompt: dict[str, Any]) -> Any:
        return choice if prompt["kind"] == "budget_exceeded" else {"decision": "approve"}

    return answer
