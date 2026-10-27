from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from agent.agents.base import load_role
from agent.agents.team import LEAD_MODEL_CALLS, build_team


class ScriptedModel(GenericFakeChatModel):
    """Replays scripted AI messages and records which tools each call could see."""

    seen_tools: ClassVar[list[list[str]]] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        self.seen_tools.append([convert_to_openai_tool(t)["function"]["name"] for t in tools])
        return self


def call(name: str, args: dict[str, Any], id_: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id_, "type": "tool_call"}])


def test_role_configs_load() -> None:
    assert load_role("project_manager").tools == ("write_todos", "task", "ls", "read_file")
    assert "write_file" in load_role("business_analyst").tools


async def test_pm_plans_delegates_and_ba_writes_into_the_workspace(tmp_path: Path) -> None:
    script = iter(
        [
            # Project Manager
            call("write_todos", {"todos": [{"content": "Write intake notes", "status": "in_progress"}]}, "c1"),
            call(
                "task",
                {"description": "Write /intake/notes.md with the goals.", "subagent_type": "business-analyst"},
                "c2",
            ),
            # Business Analyst: tries a tool it doesn't have, then writes the file
            call("delete", {"file_path": "/intake/keep.md"}, "c3"),
            call("write_file", {"file_path": "/intake/notes.md", "content": "# Goals\n- Unknown\n"}, "c4"),
            AIMessage(content="Wrote /intake/notes.md."),
            # Project Manager
            AIMessage(content="Intake notes are done. See /intake/notes.md."),
        ]
    )
    (tmp_path / "intake").mkdir()
    (tmp_path / "intake" / "keep.md").write_text("keep")
    ScriptedModel.seen_tools = []
    team = build_team(ScriptedModel(messages=script), tmp_path)
    result = await team.ainvoke({"messages": [{"role": "user", "content": "Start intake."}]})

    assert (tmp_path / "intake" / "notes.md").read_text() == "# Goals\n- Unknown\n"
    assert result["messages"][-1].content.startswith("Intake notes are done")
    # Every model call saw only its role's tools.
    allowed = {"write_todos", "task", "ls", "read_file", "write_file"}
    assert all(set(tools) <= allowed for tools in ScriptedModel.seen_tools)
    assert not any("grep" in tools or "delete" in tools for tools in ScriptedModel.seen_tools)
    # The Business Analyst's `delete` call was refused, not executed.
    assert (tmp_path / "intake" / "keep.md").read_text() == "keep"


async def test_file_system_cannot_escape_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    script = iter(
        [
            call("task", {"description": "write", "subagent_type": "business-analyst"}, "c1"),
            call("write_file", {"file_path": "/../escaped.md", "content": "x"}, "c2"),
            AIMessage(content="done"),
            AIMessage(content="done"),
        ]
    )
    team = build_team(ScriptedModel(messages=script), workspace)
    await team.ainvoke({"messages": [{"role": "user", "content": "go"}]})
    assert not (tmp_path / "escaped.md").exists()


def test_prompts_are_small() -> None:
    for role in ("project_manager", "business_analyst"):
        assert len(load_role(role).prompt) < 1200, role


async def test_a_looping_agent_is_stopped_by_the_call_limit(tmp_path: Path) -> None:
    # The Project Manager asks for `ls` forever; the cap ends the loop instead of filling the context.
    endless = iter(call("ls", {"path": "/"}, f"c{i}") for i in range(100))
    model = ScriptedModel(messages=endless)
    result = await build_team(model, tmp_path).ainvoke({"messages": [{"role": "user", "content": "look around"}]})
    ai_calls = [m for m in result["messages"] if m.type == "ai" and m.tool_calls]
    assert len(ai_calls) <= LEAD_MODEL_CALLS
