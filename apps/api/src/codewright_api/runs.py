"""In-process run manager: runs playbooks in the background (README Sections 3.3 and 9.2).

- One LangGraph graph per playbook, checkpointed in Postgres (`thread_id` = run id); one active run at a time.
- Streams each run with LangGraph v2 stream parts (ADR 0014): durable events (steps, plan, gates) are stored and fanned
  out; LLM tokens and sub-agent activity from agent loops are published live.
- On startup, resumes runs that were running when the process stopped (crash, restart, `docker kill`).
- A run waiting at a prompt (gate, model server unavailable, budget) resumes when the user answers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StreamMode
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.llm.budgets import limits_for_tier
from agent.llm.client import LLMClient, TraceSink
from agent.llm.config import ProfileName
from agent.llm.langchain_model import chat_model
from agent.playbooks.llm_step import RunStopped
from agent.playbooks.plan import plan_from
from agent.playbooks.registry import Playbook, get_playbook, playbooks
from agent.playbooks.services import ProjectTools
from agent.playbooks.state import RunState, empty_budget
from codewright_api.db import Approval, Project, Run, RunEvent
from codewright_api.llm_settings import EffectiveLLM, effective_llm
from codewright_api.settings import Settings
from codewright_api.tracing import FanOutTraceSink, LangfuseTraceSink, PostgresTraceSink, langfuse_client

if TYPE_CHECKING:  # graph.py imports this module (EventBus)
    from codewright_api.graph import GraphService
    from codewright_api.sandbox import SandboxService
    from codewright_api.verification import VerificationService

log = logging.getLogger(__name__)

ACTIVE_STATUSES = ("created", "running", "waiting")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")
STREAM_MODES: list[StreamMode] = ["updates", "messages", "custom"]


class RunConflict(Exception):
    """The request doesn't fit the run's current state (e.g. answering a gate that isn't open)."""


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=5000)
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
    """`RunServices` for playbook nodes, backed by this run manager."""

    def __init__(self, manager: RunManager) -> None:
        self._manager = manager

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
        await self._manager.record_event(uuid.UUID(run_id), event, step=step, data=data or {})

    def _tracer(self, run_id: str, step: str, role: str) -> TraceSink:
        rid = uuid.UUID(run_id)
        tracer: TraceSink = PostgresTraceSink(self._manager.sessions, run_id=rid, step=step, role=role)
        if self._manager.langfuse is not None:
            tracer = FanOutTraceSink(
                tracer, LangfuseTraceSink(self._manager.langfuse, run_id=rid, step=step, role=role)
            )
        return tracer

    def llm(self, profile: ProfileName, *, run_id: str, step: str, role: str) -> LLMClient:
        return self._manager.llm.client(profile, self._tracer(run_id, step, role))

    def chat_model(self, profile: ProfileName, *, run_id: str, step: str, role: str, **kwargs: Any) -> BaseChatModel:
        client = self._manager.llm.client(profile, self._tracer(run_id, step, role))
        return chat_model(client, trace_name=f"{step}_agent", **kwargs)

    def project(self, project_id: str) -> ProjectTools:
        from codewright_api.project_tools import ApiProjectTools  # noqa: PLC0415  (imports graph.py, which imports us)

        if self._manager.graphs is None:
            raise RuntimeError("The run manager has no project services attached.")
        return ApiProjectTools(
            project_id, self._manager.sessions, self._manager.graphs, self._manager.sandbox, self._manager.verification
        )


class _StreamTranslator:
    """Turns LangGraph v2 stream parts from agent loops into live events for the UI (ADR 0014).

    - `messages`: LLM tokens → ephemeral `token` events (published, not stored).
    - `updates` inside an agent (namespace below a playbook node): tool calls and results → stored `agent_activity`.
    - `updates` with `__interrupt__`: the run's open prompt.
    """

    def __init__(self, manager: RunManager, run_id: uuid.UUID) -> None:
        self.manager = manager
        self.run_id = run_id
        self.interrupts: list[Any] = []

    async def handle(self, part: dict[str, Any]) -> None:
        kind, ns, data = part["type"], tuple(part.get("ns") or ()), part["data"]
        if kind == "updates":
            if "__interrupt__" in data:
                self.interrupts.extend(data["__interrupt__"])
            elif len(ns) >= 1:  # inside a playbook node: an agent loop or a playbook sub-graph
                await self._activity(ns, data)
        elif kind == "messages":
            message, metadata = data
            if isinstance(message, AIMessageChunk) and isinstance(message.content, str) and message.content:
                self.manager.bus.publish(
                    str(self.run_id),
                    {
                        "id": None,
                        "type": "token",
                        "data": {
                            "agent": metadata.get("lc_agent_name") or _ns_label(ns),
                            "node": metadata.get("langgraph_node"),
                            "text": message.content,
                        },
                    },
                )

    async def _activity(self, ns: tuple[str, ...], data: dict[str, Any]) -> None:
        for node, update_ in data.items():
            messages = (update_ or {}).get("messages") if isinstance(update_, dict) else None
            if not messages:
                continue
            last = messages[-1] if isinstance(messages, list) else messages
            agent = _ns_label(ns)
            if isinstance(last, AIMessage) and last.tool_calls:
                calls = [
                    {"name": c["name"], "target": c["args"].get("subagent_type") or c["args"].get("file_path")}
                    for c in last.tool_calls
                ]
                await self.manager.record_event(
                    self.run_id, "agent_activity", data={"agent": agent, "node": node, "tool_calls": calls}
                )
            elif isinstance(last, ToolMessage):
                await self.manager.record_event(
                    self.run_id,
                    "agent_activity",
                    data={"agent": agent, "node": node, "tool_result": last.name, "status": last.status},
                )


def _ns_label(ns: tuple[str, ...]) -> str:
    """`("work:<id>", "tools:<id>")` → "work / sub-agent"; the playbook node is the first segment."""
    if not ns:
        return "run"
    parts = [ns[0].split(":")[0]]
    if any(seg.startswith("tools:") for seg in ns[1:]):
        parts.append("sub-agent")
    return " / ".join(parts)


class RunManager:
    def __init__(self, settings: Settings, sessions: async_sessionmaker[AsyncSession], database_url: str) -> None:
        self.settings = settings
        self.sessions = sessions
        self.bus = EventBus()
        self._database_url = database_url
        self._stack = AsyncExitStack()
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._graphs: dict[str, CompiledStateGraph[Any, Any, Any, Any]] = {}
        self._llm: EffectiveLLM | None = None
        self.langfuse: Any | None = langfuse_client()
        # Project services for playbooks with `needs_project` (attached by the app after creating them).
        self.graphs: GraphService | None = None
        self.sandbox: SandboxService | None = None
        self.verification: VerificationService | None = None
        # Called after every status change (the chat posts run updates and the Done card).
        self.status_listeners: list[Callable[[uuid.UUID, str], Awaitable[None]]] = []

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def start(self) -> None:
        saver = await self._stack.enter_async_context(AsyncPostgresSaver.from_conn_string(self._database_url))
        await saver.setup()
        services = _Services(self)
        self._graphs = {name: pb.spec.build(services).compile(checkpointer=saver) for name, pb in playbooks().items()}
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

    def graph(self, playbook: str) -> CompiledStateGraph[Any, Any, Any, Any]:
        if not self._graphs:
            raise RuntimeError("RunManager not started")
        return self._graphs[playbook]

    async def state_values(self, run: Run) -> dict[str, Any]:
        """The run's latest checkpointed state (plan, artifacts, step results...), empty before the first step."""
        if run.playbook not in self._graphs:
            return {}
        snapshot = await self.graph(run.playbook).aget_state({"configurable": {"thread_id": str(run.id)}})
        return dict(snapshot.values or {})

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
        for listener in self.status_listeners:
            try:
                await listener(run_id, status)
            except Exception:
                log.exception("run status listener failed for %s", run_id)

    # ── commands ─────────────────────────────────────────────────────────────
    async def create_run(
        self,
        *,
        playbook: str,
        inputs: dict[str, Any],
        project_name: str | None = None,
        llm_profile: ProfileName | None = None,
        tier: int | None = None,
        conversation_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> Run:
        """Start a playbook. `tier` may raise the playbook's default tier (more approvals), never lower it."""
        pb: Playbook = get_playbook(playbook)
        validated = pb.spec.inputs.model_validate(inputs).model_dump(mode="json")
        async with self.sessions() as session:
            active = await session.scalar(select(Run.id).where(Run.status.in_(ACTIVE_STATUSES)).limit(1))
            if active:
                raise RunConflict(f"Run {active} is still active. Codewright runs one job at a time.")
            if pb.spec.needs_project and project_id is None:
                raise ValueError(f"The {pb.title} playbook works on a project: start it from a project chat.")
            if project_name and project_id is None:
                project = Project(name=project_name, status="active")
                session.add(project)
                await session.flush()
                project_id = project.id
            run = Run(
                project_id=project_id,
                playbook=pb.name,
                tier=max(pb.tier, pb.spec.min_tier(validated), tier if tier is not None else 0),
                status="created",
                llm_profile=llm_profile or self.llm.active_profile,
                inputs=validated,
                conversation_id=conversation_id,
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

        health = await self.llm.client(run.llm_profile).health()  # type: ignore[arg-type]
        await self.record_event(
            run.id,
            "llm_health",
            data={"profile": run.llm_profile, "status": health.status, "warnings": list(health.warnings)},
        )
        self._spawn(run.id, run.playbook, await self._initial_state(run.id))
        return run

    async def answer(self, run_id: uuid.UUID, answer: Any) -> None:
        """Resume a waiting run with the user's answer to its open prompt."""
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
            else:  # llm_unavailable | budget_exceeded: one of the offered options
                if answer not in pending["options"]:
                    raise RunConflict(f"Choose one of: {', '.join(pending['options'])}.")
                if answer == "switch_to_cpu":
                    run.llm_profile = "local_cpu"
            run.pending = None
            run.status = "running"
            playbook = run.playbook
            await session.commit()
        await self.record_event(
            run_id, "answered", step=pending.get("step"), data={"prompt": pending, "answer": answer}
        )
        self._spawn(run_id, playbook, Command(resume=answer))

    async def cancel(self, run_id: uuid.UUID) -> None:
        task = self._tasks.pop(run_id, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._set_status(run_id, "cancelled", pending=None)

    # ── driving the graph ────────────────────────────────────────────────────
    def _spawn(self, run_id: uuid.UUID, playbook: str, graph_input: Any) -> None:
        task = asyncio.create_task(self._drive(run_id, playbook, graph_input), name=f"run-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda t: self._tasks.pop(run_id, None) if self._tasks.get(run_id) is t else None)

    async def _drive(self, run_id: uuid.UUID, playbook: str, graph_input: Any) -> None:
        config: RunnableConfig = {"configurable": {"thread_id": str(run_id)}, "recursion_limit": 200}
        await self._set_status(run_id, "running")
        stream = _StreamTranslator(self, run_id)
        try:
            async for part in self.graph(playbook).astream(
                graph_input, config, stream_mode=STREAM_MODES, subgraphs=True, version="v2"
            ):
                await stream.handle(dict(part))
        except asyncio.CancelledError:
            raise
        except RunStopped as exc:
            await self._set_status(run_id, "cancelled", error=str(exc), pending=None)
            return
        except Exception as exc:
            log.exception("run %s failed", run_id)
            await self._set_status(run_id, "failed", error=f"{type(exc).__name__}: {exc}")
            return

        if stream.interrupts:
            pending = stream.interrupts[0].value
            await self._set_status(run_id, "waiting", pending=pending)
            await self.record_event(run_id, "waiting", step=pending.get("step") or pending.get("gate"), data=pending)
        else:
            await self._set_status(run_id, "completed", current_step=None)

    async def _resume_interrupted_runs(self) -> None:
        async with self.sessions() as session:
            rows = list(
                await session.execute(select(Run.id, Run.playbook).where(Run.status.in_(("created", "running"))))
            )
        for run_id, playbook in rows:
            if playbook not in self._graphs:
                await self._set_status(run_id, "failed", error=f"Unknown playbook {playbook!r}")
                continue
            log.info("resuming run %s after restart", run_id)
            await self.record_event(run_id, "resumed_after_restart", data={})
            snapshot = await self.graph(playbook).aget_state({"configurable": {"thread_id": str(run_id)}})
            # Nothing checkpointed yet: the process died before the first step; start from the initial state.
            self._spawn(run_id, playbook, None if snapshot.values else await self._initial_state(run_id))

    async def _initial_state(self, run_id: uuid.UUID) -> RunState:
        async with self.sessions() as session:
            run = await session.get(Run, run_id)
            if run is None:
                raise LookupError(run_id)
        pb = get_playbook(run.playbook)
        folder = str(run.project_id) if run.project_id else f"_runs/{run.id}"
        workspace = self.settings.workspaces_dir / folder
        Path(workspace).mkdir(parents=True, exist_ok=True)
        return {
            "run_id": str(run.id),
            "project_id": str(run.project_id) if run.project_id else None,
            "playbook": run.playbook,
            "tier": run.tier,
            "inputs": run.inputs,
            "workspace": str(workspace.resolve()),
            "llm_profile": run.llm_profile,  # type: ignore[typeddict-item]
            "started_at": run.created_at.timestamp(),
            "limits": limits_for_tier(run.tier, playbook=run.playbook),
            "plan": plan_from(pb.spec.initial_plan(run.inputs)),
            "budget": empty_budget(),
        }


def _jsonable(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if isinstance(v, str | int | float | bool | type(None) | dict | list)}
