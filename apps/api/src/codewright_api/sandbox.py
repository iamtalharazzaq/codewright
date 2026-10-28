"""Sandbox actions for projects (CODEWRIGHT.md Phase 5, ADR 0020): build, test, lint and run each component in the
sandbox runner, with live output, test reports and previews.

One runner session per project, created on first use; sidecars are added when a run needs them. Activities (one
action on one or more components) keep their events in memory so the UI can reconnect and replay them.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.language_packs import detect_project
from agent.language_packs.base import Component, RunSpec, Step
from agent.language_packs.executor import (
    Action,
    ActionResult,
    copy_samples,
    exclude_from_git,
    migrations,
    production_like,
    run_action,
    run_spec,
    run_step,
)
from agent.tools.sandbox import SandboxClient, SandboxRequestError, SandboxUnavailable
from agent.verification import dbtrial
from codewright_api.settings import Settings

log = logging.getLogger(__name__)

MAX_EVENTS = 20_000
KEEP_ACTIVITIES = 20
SQL_SERVICES = {"postgres", "pgvector", "postgis", "mysql", "mariadb"}


@dataclass
class Activity:
    id: str
    project_id: str
    action: str
    components: list[str]
    status: str = "running"  # running, passed, failed, error
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    results: list[dict[str, Any]] = field(default_factory=list)
    previews: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    subscribers: set[asyncio.Queue[dict[str, Any] | None]] = field(default_factory=set)
    seq: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "components": self.components,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "results": self.results,
            "previews": self.previews,
            "error": self.error,
        }

    async def emit(self, event: dict[str, Any]) -> None:
        self.seq += 1
        event = {"seq": self.seq, "at": time.time(), **event}
        self.events.append(event)
        for q in self.subscribers:
            q.put_nowait(event)

    def close(self) -> None:
        for q in self.subscribers:
            q.put_nowait(None)


class SandboxService:
    def __init__(self, settings: Settings, client: SandboxClient | None = None) -> None:
        self.settings = settings
        self.client = client or SandboxClient(settings.sandbox_url)
        self.sessions: dict[str, str] = {}  # project id → runner session id
        self.activities: dict[str, Activity] = {}
        self.by_project: dict[str, deque[str]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._locks: dict[str, asyncio.Lock] = {}

    def work(self, project_id: uuid.UUID | str) -> Path:
        return self.settings.workspaces_dir / str(project_id) / "work"

    async def stop(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        for sid in list(self.sessions.values()):
            with contextlib.suppress(Exception):
                await self.client.delete_session(sid)
        await self.client.close()

    # ── status ───────────────────────────────────────────────────────────────
    def components(self, project_id: uuid.UUID | str) -> list[Component]:
        work = self.work(project_id)
        return detect_project(work) if work.is_dir() else []

    async def status(self, project_id: uuid.UUID | str) -> dict[str, Any]:
        pid = str(project_id)
        work = self.work(pid)
        components = await asyncio.to_thread(self.components, pid)
        runner: dict[str, Any] | None
        try:
            runner = await self.client.health()
        except (SandboxUnavailable, SandboxRequestError) as e:
            runner = {"error": str(e)}
        session: dict[str, Any] | None = None
        if sid := self.sessions.get(pid):
            try:
                session = await self.client.session(sid)
            except (SandboxUnavailable, SandboxRequestError):
                self.sessions.pop(pid, None)
        out = []
        for c in components:
            spec = run_spec(work, c)
            out.append(
                {
                    **c.as_dict(),
                    "language": c.pack,
                    "run": (
                        {
                            "kind": spec.kind,
                            "cmd": spec.cmd,
                            "port": spec.port,
                            "services": [s.name for s in spec.services],
                        }
                        if spec
                        else None
                    ),
                }
            )
        recent = [self.activities[a].summary() for a in self.by_project.get(pid, ()) if a in self.activities]
        return {"runner": runner, "components": out, "session": session, "activities": recent[::-1]}

    # ── sessions ─────────────────────────────────────────────────────────────
    def _lock(self, pid: str) -> asyncio.Lock:
        return self._locks.setdefault(pid, asyncio.Lock())

    async def _session(self, pid: str, services: list[dict[str, Any]] | None = None) -> str:
        async with self._lock(pid):
            sid = self.sessions.get(pid)
            if sid:
                try:
                    await self.client.session(sid)
                except SandboxRequestError:
                    sid = None  # the runner restarted or removed it
            if not sid:
                sid = str((await self.client.create_session(pid, services or []))["id"])
                self.sessions[pid] = sid
            elif services:
                await self.client.add_services(sid, services)
            return sid

    async def stop_session(self, project_id: uuid.UUID | str) -> None:
        sid = self.sessions.pop(str(project_id), None)
        if sid:
            with contextlib.suppress(SandboxRequestError):
                await self.client.delete_session(sid)

    # ── one command, and the migration trial ─────────────────────────────────
    async def exec_step(self, project_id: uuid.UUID | str, step: Step) -> dict[str, Any]:
        """Run one pack step (a dependency bump, an outdated listing) in the project's sandbox session."""
        pid = str(project_id)
        await asyncio.to_thread(exclude_from_git, self.work(pid))

        async def quiet(_event: dict[str, Any]) -> None:
            return None

        command, output = await run_step(self.client, await self._session(pid), step, quiet)
        return {"ok": command.ok, "exit_code": command.exit_code, "output": output[-20_000:]}

    async def db_trial(self, project_id: uuid.UUID | str, up_file: str, queries: list[str]) -> dict[str, Any]:
        """Apply a new migration to a fresh PostgreSQL sandbox database, then its rollback, measuring each step
        (`agent.verification.dbtrial`). `ok` is None when it could not run at all."""
        pid = str(project_id)
        work = self.work(pid)
        found = next(
            (
                (c, db)
                for c in self.components(pid)
                if (s := run_spec(work, c))
                for db in s.services
                if db.image.split("/")[-1].split(":")[0] in dbtrial.SQL_ENGINES
            ),
            None,
        )
        if found is None:
            return {"ok": None, "error": "no PostgreSQL service found in the project's compose file"}
        component, db = found
        up, down = work / up_file, work / up_file.replace(".up.sql", ".down.sql")
        if not up.is_file() or not down.is_file():
            return {"ok": None, "error": f"{up_file} and its .down.sql must both exist"}
        await self.stop_session(pid)
        sid = await self._session(pid, [db.__dict__])
        try:
            return await self._trial(sid, db.name, work, component, up, down, queries)
        finally:
            await self.stop_session(pid)

    async def _trial(
        self, sid: str, db: str, work: Path, component: Component, up: Path, down: Path, queries: list[str]
    ) -> dict[str, Any]:
        async def sql(text: str) -> tuple[bool, str]:
            out = await self.client.run_sql(sid, db, text)
            return out["code"] == 0, str(out["output"])

        async def take() -> dict[str, Any]:
            return dbtrial.snapshot((await sql(dbtrial.TABLES_SQL))[1], (await sql(dbtrial.SCHEMA_SQL))[1])

        async def plans() -> list[str]:
            return [dbtrial.plan_kind((await sql("explain " + q))[1]) for q in queries]

        for f in [m for m in migrations(work, component) if m.resolve() != up.resolve()]:
            ok, out = await sql(f.read_text(encoding="utf-8", errors="replace"))
            if not ok:
                return {"ok": None, "error": f"existing migration {f.name} failed: {out[-500:]}"}
        seeds = [
            p
            for base in ("scripts", "db", "database")
            for p in sorted((work / component.path / base).glob("seed*.sql"))
        ]
        seeded = []
        for f in seeds[:1]:
            if (await sql(f.read_text(encoding="utf-8", errors="replace")))[0]:
                seeded.append(f.name)
        before, plans_before = await take(), await plans()
        up_ok, up_out = await sql(up.read_text(encoding="utf-8"))
        after, plans_after = (await take(), await plans()) if up_ok else (before, plans_before)
        down_ok, down_out = (await sql(down.read_text(encoding="utf-8"))) if up_ok else (False, "not run")
        restored = await take() if down_ok else None
        return {
            "ok": up_ok and down_ok and restored is not None and dbtrial.identical(before, restored),
            "seeded": seeded,
            "rows_before": sum(int(t["rows"]) for t in before["tables"].values()),
            "up": {"ok": up_ok, "error": "" if up_ok else up_out[-800:]},
            "down": {"ok": down_ok, "error": "" if down_ok else down_out[-800:]},
            "changes": dbtrial.diff(before, after),
            "rollback_restores": restored is not None and dbtrial.identical(before, restored),
            "rollback_differences": dbtrial.diff(before, restored) if restored is not None else None,
            "queries": [
                {"query": q, "before": b, "after": a}
                for q, b, a in zip(queries, plans_before, plans_after, strict=False)
            ],
        }

    # ── actions ──────────────────────────────────────────────────────────────
    def start(self, project_id: uuid.UUID | str, action: Action, paths: list[str] | None = None) -> Activity:
        pid = str(project_id)
        components = self.components(pid)
        if paths:
            components = [c for c in components if c.path in paths]
        if action == "run":
            components = order_for_run([c for c in components if run_spec(self.work(pid), c)])
        if not components:
            raise ValueError(
                "Nothing to " + action + ": no matching component" + (" can run" if action == "run" else "")
            )
        activity = Activity(uuid.uuid4().hex[:12], pid, action, [c.path for c in components])
        self.activities[activity.id] = activity
        queue = self.by_project.setdefault(pid, deque(maxlen=KEEP_ACTIVITIES))
        if len(queue) == queue.maxlen:
            self.activities.pop(queue[0], None)
        queue.append(activity.id)
        task = asyncio.create_task(self._run(activity, components))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return activity

    async def _run(self, activity: Activity, components: list[Component]) -> None:
        work = self.work(activity.project_id)
        try:
            await asyncio.to_thread(exclude_from_git, work)
            sid = await self._session(activity.project_id)
            started: dict[str, dict[str, Any]] = {}  # component path → its web preview
            for c in components:
                await activity.emit({"type": "component", "path": c.path, "pack": c.pack, "kind": c.kind})
                copied = await asyncio.to_thread(copy_samples, work, c)
                for line in copied:
                    await activity.emit({"type": "note", "text": f"Using the sample config: {line} (not committed)"})
                if activity.action == "run":
                    result = await self._run_component(activity, sid, work, c, started)
                else:
                    result = await run_action(self.client, sid, work, c, activity.action, activity.emit)  # type: ignore[arg-type]
                activity.results.append(result.as_dict())
                await activity.emit({"type": "result", "result": result.as_dict()})
            ok = all(r["ok"] for r in activity.results)
            activity.status = "passed" if ok else "failed"
        except (SandboxUnavailable, SandboxRequestError, ValueError) as e:
            activity.status, activity.error = "error", str(e)
            await activity.emit({"type": "error", "message": str(e)})
        except Exception as e:
            log.exception("sandbox activity %s failed", activity.id)
            activity.status, activity.error = "error", f"{e.__class__.__name__}: {e}"
            await activity.emit({"type": "error", "message": activity.error})
        finally:
            activity.finished_at = time.time()
            await activity.emit({"type": "done", "status": activity.status, "error": activity.error})
            activity.close()

    async def _run_component(
        self, activity: Activity, sid: str, work: Path, c: Component, started: dict[str, dict[str, Any]]
    ) -> ActionResult:
        result = ActionResult("run", c.path, c.pack)
        spec = run_spec(work, c)
        if spec is None:  # start() only passes runnable components
            raise ValueError(f"{c.path} has nothing to run")
        flagged = production_like(spec.env, [s.name for s in spec.services])
        if flagged:
            result.error = (
                "Refused: these settings point at servers Codewright didn't create (it only runs against sandbox "
                "databases): " + ", ".join(flagged)
            )
            await activity.emit({"type": "error", "message": result.error})
            return result
        for step in spec.prepare:
            command, _ = await run_step(self.client, sid, step, activity.emit)
            result.steps.append(command)
            if not command.ok:
                return result
        if spec.services:
            names = ", ".join(f"{s.name} ({s.image})" for s in spec.services)
            await activity.emit({"type": "note", "text": f"Starting sandbox services: {names}"})
            await self._session(activity.project_id, [s.__dict__ for s in spec.services])
            await self._migrate(activity, sid, work, c, spec)
        partner = self._partner(work, c, spec, started)
        body = {
            "kind": spec.kind,
            "toolchain": spec.toolchain,
            "cmd": spec.cmd,
            "workdir": spec.workdir,
            "env": spec.env,
            "port": spec.port,
            "name": spec.name or c.path,
            **({"share_network_of": partner} if partner else {}),
        }
        preview = await self.client.start_preview(sid, body)
        preview["component"] = c.path
        started[c.path] = preview
        activity.previews.append(preview)
        await activity.emit({"type": "preview", "preview": preview})
        result.ok = True
        return result

    async def _migrate(self, activity: Activity, sid: str, work: Path, c: Component, spec: RunSpec) -> None:
        db = next((s for s in spec.services if s.image.split("/")[-1].split(":")[0] in SQL_SERVICES), None)
        files = migrations(work, c)
        if db is None or not files:
            return
        for f in files:
            sql = f.read_text(encoding="utf-8", errors="replace")
            outcome = await self.client.run_sql(sid, db.name, sql)
            ok = outcome["code"] == 0
            text = f"Migration {f.name} on {db.name}: " + ("applied" if ok else "failed")
            await activity.emit({"type": "note", "text": text, "output": "" if ok else outcome["output"][-2000:]})
            if not ok:
                break

    def _partner(self, work: Path, c: Component, spec: RunSpec, started: dict[str, dict[str, Any]]) -> str | None:
        """A frontend whose dev server proxies to `localhost:<port>` of an API we started shares its network."""
        if spec.kind != "web" or c.kind != "web":
            return None
        config = " ".join(
            (work / c.path / name).read_text(encoding="utf-8", errors="replace")
            for name in (
                "vite.config.ts",
                "vite.config.js",
                "vite.config.mjs",
                "next.config.js",
                "next.config.ts",
                "next.config.mjs",
                "package.json",
            )
            if (work / c.path / name).is_file()
        )
        for preview in started.values():
            port = preview.get("port")
            if port and (f"localhost:{port}" in config or f"127.0.0.1:{port}" in config):
                return str(preview["id"])
        return None

    async def wait(self, activity_id: str) -> Activity:
        """Until the activity has finished (playbooks use this; the UI follows the events instead)."""
        activity = self.activities[activity_id]
        while activity.status == "running":
            await asyncio.sleep(0.5)
        return activity

    async def follow(self, activity_id: str, after: int = 0) -> Any:
        activity = self.activities.get(activity_id)
        if activity is None:
            raise KeyError(activity_id)
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        for e in list(activity.events):
            if e["seq"] > after:
                q.put_nowait(e)
        if activity.finished_at is not None:
            q.put_nowait(None)
        else:
            activity.subscribers.add(q)
        try:
            while (event := await q.get()) is not None:
                yield event
        finally:
            activity.subscribers.discard(q)

    # ── previews ─────────────────────────────────────────────────────────────
    def session_of(self, project_id: uuid.UUID | str) -> str:
        sid = self.sessions.get(str(project_id))
        if not sid:
            raise KeyError("no sandbox session for this project")
        return sid


def step_outputs(activity: Activity, max_chars: int = 200_000) -> list[dict[str, Any]]:
    """An activity's output per component and step: [{component, pack, step, ok, exit_code, output}]."""
    steps: list[dict[str, Any]] = []
    component, pack = ".", ""
    current: dict[str, Any] | None = None
    for event in activity.events:
        kind = event.get("type")
        if kind == "component":
            component, pack = event.get("path", "."), event.get("pack", "")
        elif kind == "step":
            current = {"component": component, "pack": pack, "step": event.get("name"), "ok": None,
                       "exit_code": None, "output": ""}  # fmt: skip
            steps.append(current)
        elif kind == "output" and current is not None and len(current["output"]) < max_chars:
            current["output"] += event.get("text", "")
        elif kind == "step_done" and current is not None:
            result = event.get("result", {})
            current.update(ok=result.get("ok"), exit_code=result.get("exit_code"))
    if activity.error:
        steps.append({"component": ".", "pack": "", "step": "error", "ok": False, "exit_code": None,
                      "output": activity.error})  # fmt: skip
    return steps


def order_for_run(components: list[Component]) -> list[Component]:
    """APIs before the web apps that call them; then the rest."""
    rank = {"api": 0, "app": 1, "web": 2, "cli": 3}
    return sorted(components, key=lambda c: (rank.get(c.kind, 4), c.path))
