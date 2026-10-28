"""`ProjectTools` for playbook nodes (agent/playbooks/services.py): a project's graph, search, sandbox linters and
user facts, backed by the API's services. Nodes never see the database, the bus or the sandbox client directly."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.chat.corrections import describe
from codewright_api.db import MemoryItem, Project
from codewright_api.graph import GraphService
from codewright_api.sandbox import SandboxService, step_outputs
from codewright_api.verification import VerificationService

ACTION_TIMEOUT_S = 900
SCRATCH = "scratch-"
VERIFY_TIMEOUT_S = 1500


class ApiProjectTools:
    def __init__(
        self,
        project_id: str,
        sessions: async_sessionmaker[AsyncSession],
        graphs: GraphService,
        sandbox: SandboxService | None,
        verification: VerificationService | None = None,
    ) -> None:
        # A project's id, or `scratch-<run id>` for Write code's throwaway workspace (no graph, search or facts).
        self.key = project_id  # what the workspace and the sandbox know it by
        self.id = uuid.UUID(project_id.removeprefix(SCRATCH))
        self.sessions = sessions
        self.graphs = graphs
        self._sandbox = sandbox
        self._verification = verification

    @property
    def work(self) -> Path:
        return self.graphs.workspace(self.key).work

    async def summary(self) -> dict[str, Any]:
        async with self.sessions() as session:
            project = await session.get(Project, self.id)
            return {**(project.summary or {}), "name": project.name} if project else {}

    async def fresh_graph(self) -> dict[str, Any] | None:
        store = self.graphs.store(self.id)
        if not store.versions() and not self.graphs.building(self.id):
            self.graphs.refresh(self.id, reason="audit")
        await self.graphs.wait(self.id)
        return store.modules()

    def graph_versions(self) -> list[dict[str, Any]]:
        return self.graphs.store(self.id).versions()

    def explain(self, name: str) -> str:
        return self.graphs.store(self.id).explain(name)

    async def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        return await self.graphs.search(self.id, query, limit=limit)

    async def lint(self, paths: list[str] | None = None) -> list[dict[str, Any]]:
        return await self.sandbox("lint", paths)

    async def sandbox(self, action: str, paths: list[str] | None = None) -> list[dict[str, Any]]:
        if self._sandbox is None:
            return []
        activity = self._sandbox.start(self.key, action, paths)  # type: ignore[arg-type]
        await asyncio.wait_for(self._sandbox.wait(activity.id), ACTION_TIMEOUT_S)
        return step_outputs(activity)

    async def test(self, paths: list[str] | None = None) -> list[dict[str, Any]]:
        if self._sandbox is None:
            return []
        activity = self._sandbox.start(self.key, "test", paths)
        await asyncio.wait_for(self._sandbox.wait(activity.id), ACTION_TIMEOUT_S)
        if activity.error and not activity.results:
            return [{"component": ".", "pack": "", "ok": False, "error": activity.error, "report": None}]
        return activity.results

    def recordings(self) -> list[dict[str, Any]]:
        return self._verification.recordings(self.id) if self._verification is not None else []

    async def verify(self, action: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._verification is None:
            return {"ok": None, "error": "verification is not available", "report": None}
        try:
            activity = self._verification.start(self.id, action, options or {})  # type: ignore[arg-type]
        except (ValueError, KeyError) as exc:
            return {"ok": None, "error": str(exc), "report": None}
        await asyncio.wait_for(self._verification.wait(activity.id), VERIFY_TIMEOUT_S)
        report = activity.results[-1] if activity.results else None
        if activity.status == "error":
            return {"ok": None, "error": activity.error, "report": report}
        return {"ok": activity.status == "passed", "error": activity.error, "report": report}

    def files_changed(self, paths: list[str]) -> None:
        self.graphs.refresh(self.id, paths, reason="docs")

    def facts(self) -> list[dict[str, Any]]:
        return self.graphs.store(self.id).facts()

    async def add_facts(self, facts: list[dict[str, Any]]) -> None:
        await save_facts(self.sessions, self.graphs, self.id, facts)


async def save_facts(
    sessions: async_sessionmaker[AsyncSession], graphs: GraphService, project_id: uuid.UUID, facts: list[dict[str, Any]]
) -> None:
    """Confirmed facts (USER_FACT) on the graph and in project memory: one memory item per pair of modules, like the
    graph keeps them, so a newer fact about the same pair replaces the older one."""
    graphs.store(project_id).add_facts(facts)
    async with sessions() as session:
        for fact in facts:
            key = f"fact: {fact['source']} -> {fact['target']}"[:200]
            row = await session.scalar(
                select(MemoryItem).where(MemoryItem.project_id == project_id, MemoryItem.key == key)
            )
            if row is None:
                session.add(MemoryItem(project_id=project_id, key=key, value=describe(fact), source="user"))
            else:
                row.value = describe(fact)
        await session.commit()
    graphs.facts_changed(project_id)
