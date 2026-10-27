"""Project graphs and code search (CODEWRIGHT.md Section 8.2, Phase 4).

`GraphService.refresh(project, paths)` asks for a graph update. Updates are throttled per project: while one is
running, more requests just mark the graph dirty and one more update follows, at least `MIN_INTERVAL` later. Each
update saves a version and publishes a `graph` event (the diff) on the bus key `project:<id>`, so the Graph tab
grows live while something is being built. `working` events name the modules being changed right now.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.graphify import GraphifyError, GraphStore
from agent.knowledge_graph import module_of
from agent.tools.code_search import Embedder, chunk_tree, vector_literal
from agent.tools.workspace import Workspace
from codewright_api.runs import EventBus
from codewright_api.settings import Settings

log = logging.getLogger(__name__)

MIN_INTERVAL = 3.0  # seconds between two updates of one project's graph
EMBED_BATCH = 32
SEARCH_LIMIT = 8


def bus_key(project_id: uuid.UUID | str) -> str:
    return f"project:{project_id}"


class GraphService:
    def __init__(self, settings: Settings, sessions: async_sessionmaker[AsyncSession], bus: EventBus) -> None:
        self.settings = settings
        self.sessions = sessions
        self.bus = bus
        emb = settings.load_models().embeddings
        self.embedder = Embedder(emb.base_url, emb.model, emb.dimensions)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._dirty: dict[str, set[str]] = {}
        self._last: dict[str, float] = {}

    def store(self, project_id: uuid.UUID | str) -> GraphStore:
        return GraphStore(self.settings.workspaces_dir / str(project_id) / "graph")

    def workspace(self, project_id: uuid.UUID | str) -> Workspace:
        return Workspace(self.settings.workspaces_dir, str(project_id))

    def building(self, project_id: uuid.UUID | str) -> bool:
        task = self._tasks.get(str(project_id))
        return task is not None and not task.done()

    # ── live updates ─────────────────────────────────────────────────────────
    def refresh(self, project_id: uuid.UUID | str, paths: list[str] | None = None, reason: str = "update") -> None:
        """Ask for a graph update (and a search re-index). Cheap to call after every written file."""
        key = str(project_id)
        modules = sorted({m for p in paths or [] if (m := module_of(p)) is not None})
        if modules:
            self.bus.publish(bus_key(key), {"type": "working", "modules": modules})
        self._dirty.setdefault(key, set()).update(paths or ["*"])
        if not self.building(key):
            self._tasks[key] = asyncio.create_task(self._loop(key, reason))

    async def _loop(self, key: str, reason: str) -> None:
        while self._dirty.get(key):
            wait = self._last.get(key, 0) + MIN_INTERVAL - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._dirty[key] = set()
            self._last[key] = time.monotonic()
            await self._update(key, reason)

    async def _update(self, key: str, reason: str) -> None:
        ws = self.workspace(key)
        if not ws.work.is_dir():
            return
        self.bus.publish(bus_key(key), {"type": "graph_building"})
        try:
            version = await asyncio.to_thread(self.store(key).build, ws.work, reason)
        except (GraphifyError, OSError, ValueError) as exc:
            log.warning("graph build failed for %s: %s", key, exc)
            self.bus.publish(bus_key(key), {"type": "graph_error", "error": str(exc)})
            return
        self.bus.publish(bus_key(key), {"type": "graph", "version": version.as_dict()})
        try:
            await self.index(uuid.UUID(key))
        except Exception:
            log.exception("code search indexing failed for %s", key)

    async def wait(self, project_id: uuid.UUID | str) -> None:
        task = self._tasks.get(str(project_id))
        if task is not None:
            with contextlib.suppress(Exception):
                await task

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()

    # ── code search ──────────────────────────────────────────────────────────
    async def index(self, project_id: uuid.UUID) -> int:
        chunks = await asyncio.to_thread(chunk_tree, self.workspace(project_id).work)
        vectors: list[list[float] | None] = [None] * len(chunks)
        if self.embedder.available:
            for start in range(0, len(chunks), EMBED_BATCH):
                batch = chunks[start : start + EMBED_BATCH]
                got = await self.embedder.embed([f"{c.path}\n{c.content}" for c in batch])
                if got is None:
                    break
                vectors[start : start + len(batch)] = got
        async with self.sessions() as session:
            await session.execute(text("DELETE FROM code_chunks WHERE project_id = :p"), {"p": project_id})
            rows = [
                {
                    "p": project_id,
                    "path": c.path,
                    "s": c.start_line,
                    "e": c.end_line,
                    "c": c.content.replace("\x00", ""),
                    "v": vector_literal(v) if v is not None else None,
                }
                for c, v in zip(chunks, vectors, strict=True)
            ]
            if rows:
                await session.execute(
                    text(
                        "INSERT INTO code_chunks (project_id, path, start_line, end_line, content, embedding) "
                        "VALUES (:p, :path, :s, :e, :c, CAST(:v AS vector))"
                    ),
                    rows,
                )
            await session.commit()
        return len(chunks)

    async def search(self, project_id: uuid.UUID, query: str, limit: int = SEARCH_LIMIT) -> list[dict[str, Any]]:
        """Vector search when there are embeddings, full-text otherwise; results carry `match` to say which."""
        hits: list[dict[str, Any]] = []
        vector = await self.embedder.embed([query]) if self.embedder.available else None
        async with self.sessions() as session:
            if vector is not None:
                result = await session.execute(
                    text(
                        "SELECT path, start_line, end_line, content, 1 - (embedding <=> CAST(:v AS vector)) AS score "
                        "FROM code_chunks WHERE project_id = :p AND embedding IS NOT NULL "
                        "ORDER BY embedding <=> CAST(:v AS vector) LIMIT :n"
                    ),
                    {"p": project_id, "v": vector_literal(vector[0]), "n": limit},
                )
                hits = [{**r._asdict(), "match": "semantic"} for r in result]
            if not hits:
                # Any of the words, ranked; identifiers are split on _ . / like the indexed text.
                words = " | ".join(w for w in query.replace("_", " ").replace(".", " ").split() if w.isalnum())
                if words:
                    result = await session.execute(
                        text(
                            "SELECT path, start_line, end_line, content, ts_rank(tsv, q) AS score "
                            "FROM code_chunks, to_tsquery('simple', :q) q "
                            "WHERE project_id = :p AND tsv @@ q ORDER BY score DESC LIMIT :n"
                        ),
                        {"p": project_id, "q": words, "n": limit},
                    )
                    hits = [{**r._asdict(), "match": "keyword"} for r in result]
        return hits
