"""The Verification engine for projects (CODEWRIGHT.md Phase 7): characterization journeys, traffic recordings,
replays with a semantic diff and noise rules, test runs with coverage, and their reports for the Tests tab.

Everything runs against the app in the sandbox. A recording and a replay each start from a **reset**: a new sandbox
session (fresh sidecar databases with the migrations applied) and a fresh start of the app, so the same requests
meet the same state. Files live in the workspace, next to the project's runs:

    verification/journeys.json      what Codewright sends (smoke + QA-written; the user may edit it)
    verification/noise.json         the project's noise-rule choices and own rules
    verification/recordings/*.json  recorded traffic
    verification/reports/*.json     replays, recordings, test runs, benchmarks, screenshots
    .codewright/screens/<run>/      screenshots (in the work tree, where the browser container writes them)

Benchmarks (k6), screenshots (Playwright) and the live recorder (mitmproxy) run as sandbox processes that share the
app's network, so they reach it on `localhost` like a user on the same machine would.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from agent.language_packs.base import Component
from agent.language_packs.executor import run_spec
from agent.llm.client import LLMClient
from agent.verification import bench, characterize, journeys, recorder
from agent.verification.diff import Intent
from agent.verification.noise import NoiseRules
from agent.verification.replay import replay
from agent.verification.traffic import Exchange, Recording, Request, Response, from_har, is_api_call, load, save
from codewright_api.sandbox import KEEP_ACTIVITIES, Activity, SandboxService, step_outputs
from codewright_api.settings import Settings

log = logging.getLogger(__name__)

VerifyAction = Literal["characterize", "record", "replay", "test", "bench", "screens", "record-live"]
READY_TIMEOUT_S = 180
TOOL_TIMEOUT_S = 600  # a benchmark or a screenshot run
RECORD_LIVE_MAX_S = 3600  # the live recorder stops by itself after an hour
BENCH_VUS, BENCH_SECONDS = 5, 20
# The sandbox gateway's own answers while the app isn't listening yet (sandbox/runner gateway.py).
GATEWAY_WAITING = {(503, "Starting"), (502, "No preview")}
KEEP_REPORTS = 200
KEEP_SCREEN_RUNS = 10
SCREEN_CHANGED = 0.002  # share of pixels that may differ before a page counts as changed (blinking caret, a clock)


class VerificationError(RuntimeError):
    pass


@dataclass
class App:
    """The app started from a clean state: its base URL for the API (through the sandbox gateway) and the previews."""

    base: str
    preview: dict[str, Any]  # the target component's web preview
    previews: dict[str, dict[str, Any]] = field(default_factory=dict)  # component path → web preview

    @property
    def local(self) -> str:
        """The target as a process sharing its network sees it."""
        return f"http://127.0.0.1:{self.preview['port']}"


class VerificationService:
    def __init__(
        self, settings: Settings, sandbox: SandboxService, llm: Callable[[], LLMClient | None] | None = None
    ) -> None:
        self.settings = settings
        self.sandbox = sandbox
        self.llm = llm or (lambda: None)
        self.activities: dict[str, Activity] = {}
        self.by_project: dict[str, deque[str]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._busy: set[str] = set()  # projects with a verification running: one at a time (it resets the app)
        self._stops: dict[str, asyncio.Event] = {}  # project → stop its live recorder

    # ── files ────────────────────────────────────────────────────────────────
    def folder(self, project_id: uuid.UUID | str) -> Path:
        return self.settings.workspaces_dir / str(project_id) / "verification"

    def rules(self, project_id: uuid.UUID | str) -> NoiseRules:
        return NoiseRules.load(self.folder(project_id) / "noise.json")

    def saved_journeys(self, project_id: uuid.UUID | str) -> list[journeys.Journey]:
        return journeys.load_journeys(self.folder(project_id) / "journeys.json")

    def recordings(self, project_id: uuid.UUID | str) -> list[dict[str, Any]]:
        out = []
        for f in sorted((self.folder(project_id) / "recordings").glob("*.json"), reverse=True):
            with contextlib.suppress(OSError, ValueError, KeyError):
                out.append(load(f).summary())
        return out

    def recording(self, project_id: uuid.UUID | str, recording_id: str) -> Recording:
        path = self.folder(project_id) / "recordings" / f"{_safe(recording_id)}.json"
        if not path.is_file():
            raise KeyError(recording_id)
        return load(path)

    def reports(self, project_id: uuid.UUID | str, limit: int = 50) -> list[dict[str, Any]]:
        out = []
        for f in sorted((self.folder(project_id) / "reports").glob("*.json"), reverse=True)[:limit]:
            with contextlib.suppress(OSError, ValueError):
                out.append(_report_summary(json.loads(f.read_text(encoding="utf-8"))))
        return out

    def report(self, project_id: uuid.UUID | str, report_id: str) -> dict[str, Any]:
        path = self.folder(project_id) / "reports" / f"{_safe(report_id)}.json"
        if not path.is_file():
            raise KeyError(report_id)
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def save_report(self, project_id: uuid.UUID | str, report: dict[str, Any]) -> None:
        folder = self.folder(project_id) / "reports"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{report['id']}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        for old in sorted(folder.glob("*.json"))[:-KEEP_REPORTS]:
            old.unlink(missing_ok=True)

    def summary(self, project_id: uuid.UUID | str) -> dict[str, Any]:
        pid = str(project_id)
        recent = [self.activities[a].summary() for a in self.by_project.get(pid, ()) if a in self.activities]
        return {
            "recordings": self.recordings(pid),
            "reports": self.reports(pid),
            "journeys": [
                {"name": j.name, "source": j.source, "about": j.about, "steps": len(j.steps)}
                for j in self.saved_journeys(pid)
            ],
            "rules": self.rules(pid).as_list(),
            "activities": recent[::-1],
            "running": pid in self._busy,
        }

    # ── actions ──────────────────────────────────────────────────────────────
    def start(self, project_id: uuid.UUID | str, action: VerifyAction, options: dict[str, Any]) -> Activity:
        pid = str(project_id)
        if pid in self._busy:
            raise ValueError("A verification is already running for this project.")
        if action == "test":
            components = [c.path for c in self.sandbox.components(pid)]
            if options.get("component"):
                components = [c for c in components if c == options["component"]]
            if not components:
                raise ValueError("Nothing to test: no component of this project has a Language Pack.")
            component = None
        else:
            component = self._component(pid, action, options)
            components = [component.path]
        activity = Activity(uuid.uuid4().hex[:12], pid, action, components)
        self.activities[activity.id] = activity
        queue = self.by_project.setdefault(pid, deque(maxlen=KEEP_ACTIVITIES))
        if len(queue) == queue.maxlen:
            self.activities.pop(queue[0], None)
        queue.append(activity.id)
        self._busy.add(pid)
        task = asyncio.create_task(self._run(activity, component, options))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return activity

    async def wait(self, activity_id: str) -> Activity:
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

    async def stop(self) -> None:
        for t in list(self._tasks):
            t.cancel()

    def stop_recorder(self, project_id: uuid.UUID | str) -> bool:
        event = self._stops.get(str(project_id))
        if event is None:
            return False
        event.set()
        return True

    def import_har(self, project_id: uuid.UUID | str, har: dict[str, Any], component: str | None) -> dict[str, Any]:
        """A HAR file saved from a browser's developer tools → a recording (the app's API calls only)."""
        pid = str(project_id)
        target = self._target(pid, component, browsable=True)
        exchanges = from_har(har, keep=is_api_call)
        if not exchanges:
            raise ValueError("The HAR file has no API calls of the app (only pages and static files, or no entries).")
        recording = Recording(Recording.new_id(), "har", {"component": target.path, "pack": target.pack}, exchanges)
        save(recording, self.folder(pid) / "recordings")
        return recording.summary()

    def screenshot(self, project_id: uuid.UUID | str, run: str, name: str) -> Path:
        path = self.sandbox.work(project_id) / ".codewright" / "screens" / _safe(run) / _safe(name)
        if not name.endswith(".png") or not path.is_file():
            raise KeyError(name)
        return path

    def _component(self, pid: str, action: str, options: dict[str, Any]) -> Component:
        if action == "screens":
            return self._target(pid, options.get("component"), web_only=True)
        if action == "record-live":
            return self._target(pid, options.get("component"), browsable=True)
        if action in ("replay", "bench") and options.get("recording"):
            target = self.recording(pid, str(options["recording"])).target
            return self._target(pid, options.get("component") or target.get("component"))
        return self._target(pid, options.get("component"))

    def _target(self, pid: str, path: str | None, *, web_only: bool = False, browsable: bool = False) -> Component:
        """The component whose HTTP traffic is verified: the one asked for, else the first API, else the first
        web app that runs. `browsable` prefers the web app (what a user opens), `web_only` requires one."""
        work = self.sandbox.work(pid)
        runnable = [c for c in self.sandbox.components(pid) if (s := run_spec(work, c)) and s.kind == "web"]
        if path is not None:
            runnable = [c for c in runnable if c.path == path]
        if web_only:
            runnable = [c for c in runnable if c.kind == "web"]
        if not runnable:
            raise ValueError(
                "No web app of this project runs in the sandbox, so there are no pages to screenshot."
                if web_only
                else "No component of this project serves HTTP in the sandbox, so there is no traffic to verify."
            )
        first = "web" if browsable or web_only else "api"
        return next((c for c in runnable if c.kind == first), runnable[0])

    async def _run(self, activity: Activity, component: Component | None, options: dict[str, Any]) -> None:
        pid = activity.project_id
        try:
            if component is None:
                await self._test(activity)
            elif activity.action == "characterize":
                await self._characterize(activity, component)
            elif activity.action == "record":
                await self._record(activity, component, self_check=bool(options.get("self_check", True)))
            elif activity.action == "record-live":
                await self._record_live(activity, component, self_check=bool(options.get("self_check", True)))
            elif activity.action == "bench":
                await self._bench(activity, component, options.get("recording"))
            elif activity.action == "screens":
                await self._screens(activity, component, accept=bool(options.get("accept", False)))
            else:
                await self._replay(activity, component, options.get("recording"), options.get("intents") or [])
            activity.status = "failed" if activity.error else "passed"
        except (VerificationError, ValueError, KeyError) as e:
            activity.status, activity.error = "error", str(e)
            await activity.emit({"type": "error", "message": str(e)})
        except Exception as e:
            log.exception("verification %s failed", activity.id)
            activity.status, activity.error = "error", f"{e.__class__.__name__}: {e}"
            await activity.emit({"type": "error", "message": activity.error})
        finally:
            self._busy.discard(pid)
            self._stops.pop(pid, None)
            activity.finished_at = time.time()
            await activity.emit({"type": "done", "status": activity.status, "error": activity.error})
            activity.close()

    # ── tests and coverage ───────────────────────────────────────────────────
    async def _test(self, activity: Activity) -> dict[str, Any]:
        """Every component's tests in the sandbox (Language Packs, with coverage), kept as a report."""
        pid = activity.project_id
        run = self.sandbox.start(pid, "test", activity.components)
        await activity.emit({"type": "note", "text": "Running the tests of " + ", ".join(activity.components)})
        async for event in self.sandbox.follow(run.id):
            if event["type"] in ("component", "report", "result", "note", "error"):
                await activity.emit({k: v for k, v in event.items() if k not in ("seq", "at")})
        run = await self.sandbox.wait(run.id)
        components = []
        for r in run.results:
            report = r.get("report") or {}
            components.append({"path": r["component"], "pack": r["pack"], "ok": r["ok"], "error": r.get("error"),
                               "duration_s": r.get("duration_s"), "report": report,
                               "failed_step": next((s["step"] for s in r["steps"] if not s["ok"]), None)})  # fmt: skip
        counted = [c["report"] for c in components if c["report"]]
        covered = [c["coverage"] for c in counted if c.get("coverage")]
        data = {
            "id": f"tests-{time.strftime('%Y%m%d-%H%M%S')}",
            "kind": "tests",
            "started_at": run.started_at,
            "duration_s": round((run.finished_at or time.time()) - run.started_at, 1),
            "ok": run.status == "passed",
            "summary": {
                key: sum(int(c.get(key, 0)) for c in counted) for key in ("passed", "failed", "skipped", "errors")
            }
            | {
                "coverage": round(100 * sum(c["covered"] for c in covered) / sum(c["total"] for c in covered), 1)
                if covered and sum(c["total"] for c in covered)
                else None
            },
            "components": components,
            "error": run.error,
        }
        self.save_report(pid, data)
        await activity.emit({"type": "report", "report": _report_summary(data)})
        if not data["ok"]:
            activity.error = run.error or "tests failed"
        return data

    # ── the app, from a clean state ──────────────────────────────────────────
    async def fresh_app(self, activity: Activity, component: Component) -> App:
        """Reset (a new sandbox session: fresh databases, migrations applied) and start `component` (a web app with
        everything else that runs: its API); returns once the app answers HTTP."""
        pid = activity.project_id
        paths = None if component.kind == "web" else [component.path]
        started = "everything that runs" if paths is None else component.path
        await activity.emit({"type": "note", "text": f"Resetting the sandbox and starting {started}"})
        await self.sandbox.stop_session(pid)
        run = self.sandbox.start(pid, "run", paths)
        run = await self.sandbox.wait(run.id)
        preview = next((p for p in run.previews if p.get("component") == component.path and p.get("url")), None)
        if run.status != "passed" or preview is None:
            tail = "\n".join(s["output"][-1500:] for s in step_outputs(run)[-2:])
            raise VerificationError(f"The app didn't start: {run.error or 'the run failed'}\n{tail}".strip())
        port = urlsplit(str(preview["url"])).port
        base = f"http://{self.settings.sandbox_gateway_host}:{port}"
        await activity.emit(
            {"type": "note", "text": f"Waiting for {component.path} to answer on port {preview['port']}"}
        )
        await self._ready(base, pid, str(preview["id"]))
        await activity.emit({"type": "app", "base_url": base, "preview": preview})
        return App(base, preview, {str(p["component"]): p for p in run.previews if p.get("url")})

    async def _ready(self, base: str, pid: str, preview_id: str) -> None:
        deadline = time.monotonic() + READY_TIMEOUT_S
        async with httpx.AsyncClient(base_url=base, timeout=5) as http:
            while time.monotonic() < deadline:
                with contextlib.suppress(httpx.HTTPError):
                    answer = await http.get("/")
                    if (answer.status_code, answer.reason_phrase) not in GATEWAY_WAITING:
                        return  # the app's own answer, whatever its status
                state = await self.sandbox.client.preview(self.sandbox.session_of(pid), preview_id)
                if not state.get("running", True):
                    raise VerificationError(f"The app stopped while starting (exit code {state.get('exit_code')}).")
                await asyncio.sleep(1)
        raise VerificationError(f"The app didn't answer HTTP within {READY_TIMEOUT_S} s.")

    async def _plan(self, activity: Activity, component: Component, base: str) -> tuple[list[journeys.Route], str]:
        work = self.sandbox.work(activity.project_id)
        found = await asyncio.to_thread(journeys.routes, work, component.path)
        candidates = await asyncio.to_thread(journeys.prefix_candidates, work / component.path)
        async with httpx.AsyncClient(base_url=base) as http:
            prefix, how = await journeys.discover_prefix(http, found, candidates)
        await activity.emit({"type": "note", "text": f"{len(found)} routes; prefix {prefix or '(none)'}: {how}"})
        return found, prefix

    # ── characterize: write the journeys ─────────────────────────────────────
    async def _characterize(self, activity: Activity, component: Component) -> list[journeys.Journey]:
        pid = activity.project_id
        base = (await self.fresh_app(activity, component)).base
        found, prefix = await self._plan(activity, component, base)
        async with httpx.AsyncClient(base_url=base) as http:
            kept = [await journeys.smoke_journey(http, found, prefix)]
        client = self.llm()
        if client is None:
            await activity.emit({"type": "note", "text": "No model available: only the smoke journey is written."})
        else:

            async def notify(text: str) -> None:
                await activity.emit({"type": "note", "text": text})

            kept += await characterize.write_journeys(
                client, self.sandbox.work(pid), found, prefix, base, notify=notify
            )
        journeys.save_journeys(kept, self.folder(pid) / "journeys.json")
        steps = sum(len(j.steps) for j in kept)
        await activity.emit({"type": "journeys", "journeys": [j.name for j in kept], "steps": steps})
        return kept

    # ── record: send the journeys from a clean state ─────────────────────────
    async def _record(self, activity: Activity, component: Component, *, self_check: bool) -> None:
        pid = activity.project_id
        plan = self.saved_journeys(pid)
        if not plan:
            plan = await self._characterize(activity, component)
        base = (await self.fresh_app(activity, component)).base
        recording = Recording(Recording.new_id(), "journeys", {"component": component.path, "pack": component.pack})

        async def on_exchange(ex: Exchange) -> None:
            await activity.emit({"type": "exchange", "exchange": _brief(ex)})

        await journeys.run_journeys(plan, base, recording=recording, on_exchange=on_exchange)
        if not recording.exchanges:
            raise VerificationError("Nothing was recorded: the journeys have no steps.")
        save(recording, self.folder(pid) / "recordings")
        summary = recording.summary()
        self.save_report(pid, {"id": f"record-{recording.id}", "kind": "record", "started_at": recording.created_at,
                               "ok": summary["unanswered"] == 0, **summary})  # fmt: skip
        await activity.emit({"type": "recording", "recording": summary})
        if self_check:
            await activity.emit({"type": "note", "text": "Self-check: replaying the recording on a fresh app"})
            await self._replay(activity, component, recording.id, [])

    # ── replay ───────────────────────────────────────────────────────────────
    async def _replay(
        self, activity: Activity, component: Component, recording_id: str | None, intents: list[dict[str, Any]]
    ) -> dict[str, Any]:
        pid = activity.project_id
        recording = self._latest(pid, component, recording_id)
        base = (await self.fresh_app(activity, component)).base

        async def on_result(result: dict[str, Any]) -> None:
            await activity.emit({"type": "replayed", "result": _brief_result(result)})

        report = await replay(
            recording, base, self.rules(pid), report_id=f"replay-{time.strftime('%Y%m%d-%H%M%S')}",
            intents=[Intent(**i) for i in intents], on_exchange=on_result,
        )  # fmt: skip
        data = report.as_dict()
        data["target"] = recording.target
        self.save_report(pid, data)
        counts = data["counts"]
        await activity.emit({"type": "report", "report": _report_summary(data)})
        if not report.ok:
            activity.error = f"{counts['regression']} regression(s) in {counts['exchanges']} requests"
        activity.results.append(_report_summary(data))
        return data

    def _latest(self, pid: str, component: Component, recording_id: str | None) -> Recording:
        if recording_id is None:
            listed = [r for r in self.recordings(pid) if r["target"].get("component") == component.path]
            if not listed:
                raise VerificationError("There is no recording to replay yet: record one first.")
            recording_id = str(listed[0]["id"])
        return self.recording(pid, recording_id)

    # ── tools beside the app: k6, Playwright, mitmproxy ──────────────────────
    async def _tool(
        self, activity: Activity, app: App, toolchain: str, cmd: list[str], partner: dict[str, Any] | None = None
    ) -> tuple[int | None, str]:
        """Run a command to its end in a sandbox process sharing the app's network; its exit code and output."""
        sid = self.sandbox.session_of(activity.project_id)
        spec = {"kind": "terminal", "toolchain": toolchain, "cmd": cmd, "name": cmd[0], "timeout_s": TOOL_TIMEOUT_S,
                "share_network_of": str((partner or app.preview)["id"])}  # fmt: skip
        process = await self.sandbox.client.start_preview(sid, spec)
        output = bytearray()
        try:
            async with asyncio.timeout(TOOL_TIMEOUT_S + 30):
                async for chunk in self.sandbox.client.preview_output(sid, str(process["id"])):
                    output += chunk
            state = await self.sandbox.client.preview(sid, str(process["id"]))
        finally:
            with contextlib.suppress(Exception):
                await self.sandbox.client.stop_preview(sid, str(process["id"]))
        code = state.get("exit_code")
        return (int(code) if code is not None else None), output.decode("utf-8", "replace")[-4000:]

    # ── bench: k6 on the read requests of a recording ────────────────────────
    async def _bench(self, activity: Activity, component: Component, recording_id: str | None) -> dict[str, Any]:
        """Replay the recording on a fresh app (so IDs and tokens are this run's), then load its successful GETs with
        k6 beside the app, and compare with the last benchmark of the same recording."""
        pid = activity.project_id
        recording = self._latest(pid, component, recording_id)
        app = await self.fresh_app(activity, component)
        sent: list[tuple[Request, int | None]] = []

        async def on_sent(request: Request, live: Response | None) -> None:
            sent.append((request, live.status if live else None))

        await activity.emit({"type": "note", "text": f"Replaying {recording.id} to get this run's IDs and tokens"})
        await replay(recording, app.base, self.rules(pid), report_id="bench", on_sent=on_sent)
        chosen = bench.targets(sent)
        if not chosen:
            raise VerificationError("The recording has no GET request that succeeded, so there is nothing to load.")
        work = self.sandbox.work(pid)
        folder = work / ".codewright" / "bench"
        folder.mkdir(parents=True, exist_ok=True)
        rel = ".codewright/bench"
        (folder / "summary.json").unlink(missing_ok=True)
        (folder / "script.js").write_text(
            bench.script(app.local, chosen, BENCH_VUS, BENCH_SECONDS, f"/work/{rel}/summary.json"), encoding="utf-8"
        )
        names = ", ".join(t.name for t in chosen[:6]) + (" …" if len(chosen) > 6 else "")
        await activity.emit({"type": "note", "text": f"k6: {BENCH_VUS} users for {BENCH_SECONDS} s on {names}"})
        code, output = await self._tool(activity, app, "tools", ["k6", "run", "--quiet", f"/work/{rel}/script.js"])
        if not (folder / "summary.json").is_file():
            raise VerificationError(f"k6 didn't finish (exit code {code}).\n{output[-1500:]}".strip())
        numbers = bench.read_summary(json.loads((folder / "summary.json").read_text(encoding="utf-8")))
        earlier = next((r for r in self.reports(pid, limit=200)
                        if r.get("kind") == "bench" and r.get("recording") == recording.id), None)  # fmt: skip
        data = {
            "id": f"bench-{time.strftime('%Y%m%d-%H%M%S')}",
            "kind": "bench",
            "started_at": activity.started_at,
            "ok": numbers["failed_rate"] == 0,
            "recording": recording.id,
            "target": recording.target,
            "settings": {"vus": BENCH_VUS, "duration_s": BENCH_SECONDS, "endpoints": [t.name for t in chosen]},
            "summary": numbers,
            "compared_with": earlier["id"] if earlier else None,
            "comparison": bench.compare(self.report(pid, earlier["id"])["summary"], numbers) if earlier else None,
        }
        self.save_report(pid, data)
        await activity.emit({"type": "report", "report": _report_summary(data)})
        activity.results.append(
            _report_summary(data)
        )  # so callers reading `activity.results[-1]` see it (as `_replay` does)
        if not data["ok"]:
            activity.error = f"{100 * numbers['failed_rate']:.1f}% of the benchmark's requests failed"
        return data

    # ── screens: Playwright screenshots, compared with the accepted ones ─────
    async def _screens(self, activity: Activity, component: Component, *, accept: bool) -> dict[str, Any]:
        pid = activity.project_id
        work = self.sandbox.work(pid)
        found = await asyncio.to_thread(journeys.pages, work, component.path)
        if not found:
            found = ["/"]
        app = await self.fresh_app(activity, component)
        run_id = f"screens-{time.strftime('%Y%m%d-%H%M%S')}"
        screens = work / ".codewright" / "screens"
        (screens / run_id).mkdir(parents=True, exist_ok=True)
        (screens / run_id / "pages.json").write_text(json.dumps(found), encoding="utf-8")
        baseline = screens / "baseline"
        has_baseline = (baseline / "result.json").is_file()
        out = f"/work/.codewright/screens/{run_id}"
        cmd = ["python", "/opt/codewright/shoot.py", app.local, f"{out}/pages.json", out]
        if has_baseline:
            cmd.append("/work/.codewright/screens/baseline")
        await activity.emit({"type": "note", "text": f"Screenshots of {len(found)} pages: " + ", ".join(found)})
        code, output = await self._tool(activity, app, "browser", cmd)
        result_file = screens / run_id / "result.json"
        if not result_file.is_file():
            raise VerificationError(f"The browser didn't finish (exit code {code}).\n{output[-1500:]}".strip())
        shots = json.loads(result_file.read_text(encoding="utf-8"))["pages"]
        changed = [s for s in shots if (s.get("diff_ratio") or 0) > SCREEN_CHANGED]
        if accept or not has_baseline:
            await asyncio.to_thread(shutil.rmtree, baseline, ignore_errors=True)
            await asyncio.to_thread(shutil.copytree, screens / run_id, baseline)
        data = {
            "id": run_id,
            "kind": "screens",
            "started_at": activity.started_at,
            "ok": not changed and not any("error" in s for s in shots),
            "target": {"component": component.path, "pack": component.pack},
            "summary": {
                "pages": len(shots),
                "changed": len(changed),
                "errors": sum(1 for s in shots if "error" in s),
                "baseline": "this run" if accept or not has_baseline else "earlier run",
            },
            "pages": shots,
        }
        self.save_report(pid, data)
        await activity.emit({"type": "report", "report": _report_summary(data)})
        if not data["ok"]:
            activity.error = (
                f"{len(changed)} page(s) look different from the accepted screenshots"
                if changed
                else ("some pages failed to open")
            )
        for old in sorted(p for p in screens.glob("screens-*") if p.is_dir())[:-KEEP_SCREEN_RUNS]:
            await asyncio.to_thread(shutil.rmtree, old, ignore_errors=True)
        return data

    # ── record-live: the user browses the app through mitmproxy ──────────────
    async def _record_live(self, activity: Activity, component: Component, *, self_check: bool) -> None:
        pid = activity.project_id
        stop = self._stops[pid] = asyncio.Event()
        app = await self.fresh_app(activity, component)
        work = self.sandbox.work(pid)
        (work / recorder.FILE).parent.mkdir(parents=True, exist_ok=True)
        (work / recorder.FILE).unlink(missing_ok=True)
        sid = self.sandbox.session_of(pid)
        proxy = await self.sandbox.client.start_preview(sid, {
            "kind": "web", "toolchain": "tools", "cmd": recorder.command(int(app.preview["port"])),
            "port": recorder.PORT, "name": "recorder", "share_network_of": str(app.preview["id"]),
        })  # fmt: skip
        await activity.emit({"type": "recorder", "url": proxy.get("url"), "preview": proxy,
                             "text": "Open the recorder's address and use the app; press Stop when done."})  # fmt: skip
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(RECORD_LIVE_MAX_S):
                await stop.wait()
        with contextlib.suppress(Exception):
            await self.sandbox.client.stop_preview(sid, str(proxy["id"]))
        exchanges = await asyncio.to_thread(recorder.read, work / recorder.FILE)
        if not exchanges:
            raise VerificationError("Nothing was recorded: no API call went through the recorder.")
        recording = Recording(Recording.new_id(), "recorder", {"component": component.path, "pack": component.pack},
                              exchanges)  # fmt: skip
        save(recording, self.folder(pid) / "recordings")
        summary = recording.summary()
        self.save_report(pid, {"id": f"record-{recording.id}", "kind": "record", "started_at": recording.created_at,
                               "ok": summary["unanswered"] == 0, **summary})  # fmt: skip
        await activity.emit({"type": "recording", "recording": summary})
        if self_check:
            await activity.emit({"type": "note", "text": "Self-check: replaying the recording on a fresh app"})
            await self._replay(activity, component, recording.id, [])


def _safe(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "-_.")[:120]


def _brief(ex: Exchange) -> dict[str, Any]:
    return {
        "seq": ex.seq,
        "journey": ex.journey,
        "step": ex.step,
        "method": ex.request.method,
        "path": ex.request.path,
        "status": ex.response.status if ex.response else None,
        "error": ex.error,
    }


def _brief_result(r: dict[str, Any]) -> dict[str, Any]:
    keys = ("seq", "journey", "step", "method", "path", "status_before", "status_after", "regressions", "error")
    return {k: r.get(k) for k in keys} | {"differences": len(r.get("differences", []))}


def _report_summary(data: dict[str, Any]) -> dict[str, Any]:
    keep = ("id", "kind", "started_at", "duration_s", "ok", "counts", "noise_used", "recording", "target",
            "exchanges", "endpoints", "journeys", "server_errors", "unanswered", "summary", "comparison")  # fmt: skip
    return {k: data[k] for k in keep if k in data}
