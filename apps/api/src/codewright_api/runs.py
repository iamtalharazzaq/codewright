"""In-process run manager (README Section 3: "Jobs: in-process run manager, one active run at a time").

- Drives the LangGraph workflow in a background task per run, checkpointed in Postgres.
- Persists every event (timeline) and fans it out to live SSE subscribers.
- On startup, resumes runs that were running when the process stopped (crash, restart, `docker kill`).
- A run waiting at a gate (or at a "model server unavailable" prompt) resumes when the user answers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections import defaultdict
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.graph.state import WorkflowState
from agent.graph.workflow import build_workflow
from agent.llm.client import LLMClient, TraceSink
from agent.llm.config import ProfileName
from codewright_api.db import Approval, Project, Run, RunEvent
from codewright_api.llm_settings import EffectiveLLM, effective_llm
from codewright_api.settings import Settings
from codewright_api.tracing import FanOutTraceSink, LangfuseTraceSink, PostgresTraceSink, langfuse_client

log = logging.getLogger(__name__)

ACTIVE_STATUSES = ("created", "running", "waiting")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")


class RunConflict(Exception):
    """The request doesn't fit the run's current state (e.g. answering a gate that isn't open)."""


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscribers[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers[run_id].discard(queue)

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(run_id, ())):
            with contextlib.suppress(asyncio.QueueFull):  # a stuck client must not block the run
                queue.put_nowait(event)


def event_dict(row: RunEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": str(row.run_id),
        "type": row.type,
        "step": row.step,
        "data": row.data,
        "created_at": row.created_at.isoformat(),
    }


class _Services:
    """`RunServices` for workflow nodes, backed by this run manager."""

    def __init__(self, manager: RunManager) -> None:
        self._manager = manager

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
        await self._manager.record_event(uuid.UUID(run_id), event, step=step, data=data or {})

    def llm(self, profile: ProfileName, *, run_id: str, step: str, role: str) -> LLMClient:
        rid = uuid.UUID(run_id)
        tracer: TraceSink = PostgresTraceSink(self._manager.sessions, run_id=rid, step=step, role=role)
        if self._manager.langfuse is not None:
            tracer = FanOutTraceSink(
                tracer, LangfuseTraceSink(self._manager.langfuse, run_id=rid, step=step, role=role)
            )
        return self._manager.llm.client(profile, tracer)


class RunManager:
    def __init__(self, settings: Settings, sessions: async_sessionmaker[AsyncSession], database_url: str) -> None:
        self.settings = settings
        self.sessions = sessions
        self.bus = EventBus()
        self._database_url = database_url
        self._stack = AsyncExitStack()
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._graph: CompiledStateGraph[Any, Any, Any, Any] | None = None
        self._llm: EffectiveLLM | None = None
        self.langfuse: Any | None = langfuse_client()

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def start(self) -> None:
        saver = await self._stack.enter_async_context(AsyncPostgresSaver.from_conn_string(self._database_url))
        await saver.setup()
        self._graph = build_workflow(_Services(self), saver)
        await self.refresh_llm()
        await self._resume_interrupted_runs()

    async def stop(self) -> None:
        # Cancel without changing run status: those runs resume on the next start.
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        await self._stack.aclose()
        if self.langfuse is not None:
            self.langfuse.flush()

    async def refresh_llm(self) -> EffectiveLLM:
        async with self.sessions() as session:
            self._llm = await effective_llm(session, self.settings)
        return self._llm

    @property
    def llm(self) -> EffectiveLLM:
        if self._llm is None:
            raise RuntimeError("RunManager not started")
        return self._llm

    @property
    def graph(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        if self._graph is None:
            raise RuntimeError("RunManager not started")
        return self._graph

    # ── events ───────────────────────────────────────────────────────────────
    async def record_event(
        self, run_id: uuid.UUID, type_: str, *, step: str | None = None, data: dict[str, Any]
    ) -> None:
        async with self.sessions() as session:
            row = RunEvent(run_id=run_id, type=type_, step=step, data=data)
            session.add(row)
            if type_ == "step_started":
                await session.execute(update(Run).where(Run.id == run_id).values(current_step=step))
            await session.commit()
            await session.refresh(row)
        self.bus.publish(str(run_id), event_dict(row))

    async def _set_status(self, run_id: uuid.UUID, status: str, **values: Any) -> None:
        async with self.sessions() as session:
            await session.execute(update(Run).where(Run.id == run_id).values(status=status, **values))
            await session.commit()
        await self.record_event(run_id, "run_status", data={"status": status, **_jsonable(values)})

    # ── commands ─────────────────────────────────────────────────────────────
    async def create_run(
        self, *, project_name: str, mode: str, llm_profile: ProfileName | None, options: dict[str, Any]
    ) -> Run:
        async with self.sessions() as session:
            active = await session.scalar(select(Run.id).where(Run.status.in_(ACTIVE_STATUSES)).limit(1))
            if active:
                raise RunConflict(f"Run {active} is still active. Codewright runs one job at a time.")
            profile = llm_profile or self.llm.active_profile
            project = Project(name=project_name, status="active")
            session.add(project)
            await session.flush()
            run = Run(project_id=project.id, mode=mode, status="created", llm_profile=profile, options=options)
            session.add(run)
            await session.commit()
            await session.refresh(run)

        health = await self.llm.client(profile).health()
        await self.record_event(
            run.id, "llm_health", data={"profile": profile, "status": health.status, "warnings": list(health.warnings)}
        )
        workspace = self.settings.workspaces_dir / str(project.id)
        initial: WorkflowState = {
            "project_id": str(project.id),
            "run_id": str(run.id),
            "mode": mode,  # type: ignore[typeddict-item]
            "workspace": str(workspace),
            "llm_profile": profile,
            "options": options,
        }
        Path(workspace).mkdir(parents=True, exist_ok=True)
        self._spawn(run.id, initial)
        return run

    async def answer(self, run_id: uuid.UUID, answer: Any) -> None:
        """Resume a waiting run with the user's answer to its open prompt (gate decision or recovery choice)."""
        async with self.sessions() as session:
            run = await session.get(Run, run_id)
            if run is None:
                raise LookupError(run_id)
            if run.status != "waiting" or not run.pending:
                raise RunConflict("This run is not waiting for an answer.")
            pending = run.pending
            if pending["kind"] == "gate":
                if not isinstance(answer, dict) or answer.get("decision") not in ("approve", "edit", "reject"):
                    raise RunConflict("A gate needs a decision: approve, edit or reject.")
                session.add(
                    Approval(
                        run_id=run_id,
                        gate=pending["gate"],
                        subject=pending.get("subject"),
                        decision=answer["decision"],
                        comment=answer.get("comment", ""),
                        edits=answer.get("edits", {}),
                    )
                )
            elif pending["kind"] == "llm_unavailable":
                if answer not in pending["options"]:
                    raise RunConflict(f"Choose one of: {', '.join(pending['options'])}.")
                if answer == "switch_to_cpu":
                    run.llm_profile = "local_cpu"
            run.pending = None
            run.status = "running"
            await session.commit()
        await self.record_event(
            run_id, "answered", step=pending.get("step"), data={"prompt": pending, "answer": answer}
        )
        self._spawn(run_id, Command(resume=answer))

    async def cancel(self, run_id: uuid.UUID) -> None:
        task = self._tasks.pop(run_id, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._set_status(run_id, "cancelled", pending=None)

    # ── driving the graph ────────────────────────────────────────────────────
    def _spawn(self, run_id: uuid.UUID, graph_input: Any) -> None:
        task = asyncio.create_task(self._drive(run_id, graph_input), name=f"run-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda t: self._tasks.pop(run_id, None) if self._tasks.get(run_id) is t else None)

    async def _drive(self, run_id: uuid.UUID, graph_input: Any) -> None:
        config: RunnableConfig = {"configurable": {"thread_id": str(run_id)}, "recursion_limit": 200}
        await self._set_status(run_id, "running")
        try:
            result = await self.graph.ainvoke(graph_input, config)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("run %s failed", run_id)
            await self._set_status(run_id, "failed", error=f"{type(exc).__name__}: {exc}")
            return

        interrupts = result.get("__interrupt__") or []
        if interrupts:
            pending = interrupts[0].value
            await self._set_status(run_id, "waiting", pending=pending)
            await self.record_event(run_id, "waiting", step=pending.get("step") or pending.get("gate"), data=pending)
        else:
            await self._set_status(run_id, "completed", current_step=None)

    async def _resume_interrupted_runs(self) -> None:
        async with self.sessions() as session:
            ids = list(await session.scalars(select(Run.id).where(Run.status.in_(("created", "running")))))
        for run_id in ids:
            log.info("resuming run %s after restart", run_id)
            await self.record_event(run_id, "resumed_after_restart", data={})
            snapshot = await self.graph.aget_state({"configurable": {"thread_id": str(run_id)}})
            # Nothing checkpointed yet: the process died before the first step; start from the initial state.
            self._spawn(run_id, None if snapshot.values else await self._initial_state(run_id))

    async def _initial_state(self, run_id: uuid.UUID) -> WorkflowState:
        async with self.sessions() as session:
            run = await session.get(Run, run_id)
            if run is None:
                raise LookupError(run_id)
            return {
                "project_id": str(run.project_id),
                "run_id": str(run.id),
                "mode": run.mode,  # type: ignore[typeddict-item]
                "workspace": str(self.settings.workspaces_dir / str(run.project_id)),
                "llm_profile": run.llm_profile,  # type: ignore[typeddict-item]
                "options": run.options,
            }


def _jsonable(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if isinstance(v, str | int | float | bool | type(None) | dict | list)}
