"""LangGraph v2 stream parts → UI events (ADR 0014), without a database."""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from codewright_api.runs import EventBus, _StreamTranslator


class FakeManager:
    def __init__(self) -> None:
        self.bus = EventBus()
        self.recorded: list[tuple[str, dict[str, Any]]] = []

    async def record_event(
        self, run_id: uuid.UUID, type_: str, *, step: str | None = None, data: dict[str, Any]
    ) -> None:
        self.recorded.append((type_, data))


async def test_tokens_are_live_only_and_sub_agent_tool_calls_are_recorded() -> None:
    manager = FakeManager()
    run_id = uuid.uuid4()
    live = manager.bus.subscribe(str(run_id))
    stream = _StreamTranslator(manager, run_id)  # type: ignore[arg-type]
    ns = ("work:1", "tools:2")

    await stream.handle(
        {"type": "messages", "ns": ns, "data": (AIMessageChunk(content="Hel"), {"lc_agent_name": "business-analyst"})}
    )
    call = AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"file_path": "/brief.md"}, "id": "c1"}])
    await stream.handle({"type": "updates", "ns": ns, "data": {"model": {"messages": [call]}}})
    done = ToolMessage(content="ok", name="write_file", tool_call_id="c1")
    await stream.handle({"type": "updates", "ns": ns, "data": {"tools": {"messages": [done]}}})
    await stream.handle({"type": "updates", "ns": (), "data": {"__interrupt__": ("prompt",)}})

    token = live.get_nowait()
    assert token == {"id": None, "type": "token", "data": {"agent": "business-analyst", "node": None, "text": "Hel"}}
    assert live.empty()  # nothing else is published directly; stored events go through record_event
    assert manager.recorded == [
        (
            "agent_activity",
            {
                "agent": "work / sub-agent",
                "node": "model",
                "tool_calls": [{"name": "write_file", "target": "/brief.md"}],
            },
        ),
        (
            "agent_activity",
            {"agent": "work / sub-agent", "node": "tools", "tool_result": "write_file", "status": "success"},
        ),
    ]
    assert stream.interrupts == ["prompt"]
