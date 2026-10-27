"""Pause at a gate, drop everything (as if the API process died), rebuild from Postgres and resume."""

from __future__ import annotations

import uuid
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from agent.graph.workflow import build_workflow
from agent.tests.conftest import FakeServices

from .helpers import initial_state


async def test_run_survives_a_restart(pg_url: str, tmp_path: Path) -> None:
    config: RunnableConfig = {"configurable": {"thread_id": f"test-{uuid.uuid4()}"}}

    async with AsyncPostgresSaver.from_conn_string(pg_url) as saver:
        await saver.setup()
        graph = build_workflow(FakeServices(), saver)
        result = await graph.ainvoke(initial_state(tmp_path, "audit"), config)
        assert result["__interrupt__"][0].value["gate"] == "gate1"

    # "Restart": new connection, new graph object, same thread id.
    async with AsyncPostgresSaver.from_conn_string(pg_url) as saver:
        graph = build_workflow(FakeServices(), saver)
        snapshot = await graph.aget_state(config)
        assert snapshot.next == ("gate1",)
        result = await graph.ainvoke(Command(resume={"decision": "approve"}), config)
        assert result["__interrupt__"][0].value["gate"] == "gate2"
        assert result["completed_steps"] == ["intake", "baseline", "as_is"]
