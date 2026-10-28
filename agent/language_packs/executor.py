"""Runs a pack's plans in the sandbox: build, test, lint, run (CODEWRIGHT.md Phase 5, ADR 0020).

Every action is a list of `Step`s sent one by one to the sandbox runner; output streams to `emit` as it comes. Test
steps are read back into a `TestReport` (JUnit XML or `go test -json` written under `.codewright/reports/`).
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from agent.language_packs import pack
from agent.language_packs.base import REPORTS, CommandResult, Component, RunSpec, Step, TestReport, tail
from agent.tools.sandbox import SandboxClient

Action = Literal["build", "test", "lint", "audit", "run"]
Emit = Callable[[dict[str, Any]], Awaitable[None]]
GIT_EXCLUDES = (".codewright/", "graphify-out/", "node_modules/", ".venv/")
TAIL_CHARS = 20_000


def exclude_from_git(work: Path) -> None:
    """Keep the sandbox's own files (reports, binaries, installed dependencies) out of commits and deliveries."""
    exclude = work / ".git" / "info" / "exclude"
    if not exclude.parent.is_dir():
        return
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    missing = [p for p in GIT_EXCLUDES if p not in text.split()]
    if missing:
        exclude.write_text(text.rstrip("\n") + "\n" + "\n".join(missing) + "\n", encoding="utf-8")


def plan(repo: Path, component: Component, action: Action) -> list[Step]:
    p = pack(component.pack)
    build = p.build_steps(repo, component)
    if action == "build":
        return build
    if action == "test":
        return [*build, *p.test_steps(repo, component)]
    if action == "lint":
        setup = [s for s in build if s.name in {"install", "configure"}]
        return [*setup, *p.lint_steps(repo, component)]
    if action == "audit":
        setup = [s for s in build if s.name in {"install", "configure"}]
        return [*setup, *p.audit_steps(repo, component)]
    spec = p.run_spec(repo, component)
    return spec.prepare if spec else []


def job_spec(step: Step) -> dict[str, Any]:
    cmd = step.cmd
    if step.report == "go-json":
        # keep the full JSON in a file for the report (the live output may be cut), show it live as well
        joined = " ".join(_quote(c) for c in cmd)
        cmd = ["bash", "-c", f"set -o pipefail; mkdir -p {REPORTS}; {joined} | tee {REPORTS}/go-test.json"]
    elif step.report:
        cmd = ["sh", "-c", f'mkdir -p {REPORTS} && rm -f {REPORTS}/* && exec "$@"', "sh", *cmd]
    return {
        "toolchain": step.toolchain,
        "cmd": cmd,
        "workdir": step.workdir,
        "env": step.env,
        "network": step.network,
        **({"timeout_s": step.timeout_s} if step.timeout_s else {}),
    }


def _quote(arg: str) -> str:
    return arg if arg.replace("/", "").replace(".", "").replace("-", "").replace("_", "").isalnum() else f"'{arg}'"


def _readable(text: str) -> str:
    """`go test -json` lines → their `Output` text, for people."""
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("{"):
            try:
                out.append(json.loads(line).get("Output", ""))
                continue
            except ValueError:
                pass
        out.append(line)
    return "".join(out)


@dataclass
class ActionResult:
    action: str
    component: str
    pack: str
    ok: bool = False
    steps: list[CommandResult] = field(default_factory=list)
    report: TestReport | None = None
    error: str | None = None
    duration_s: float = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "component": self.component,
            "pack": self.pack,
            "ok": self.ok,
            "steps": [{**asdict(s), "ok": s.ok} for s in self.steps],
            "report": self.report.as_dict() if self.report else None,
            "error": self.error,
            "duration_s": self.duration_s,
        }


async def run_step(client: SandboxClient, sid: str, step: Step, emit: Emit) -> tuple[CommandResult, str]:
    await emit({"type": "step", "name": step.name, "cmd": step.cmd, "workdir": step.workdir, "network": step.network})
    buffer = ""
    result = CommandResult(step.name, -1, 0)
    async for event in client.job(sid, job_spec(step)):
        kind = event.get("type")
        if kind == "output":
            text = event["text"]
            buffer = (buffer + text)[-TAIL_CHARS:]
            shown = _readable(text) if step.report == "go-json" else text
            if shown:
                await emit({"type": "output", "step": step.name, "stream": event.get("stream"), "text": shown})
        elif kind == "truncated":
            await emit({"type": "output", "step": step.name, "stream": "stderr", "text": "\n[output cut]\n"})
        elif kind == "exit":
            result = CommandResult(
                step.name,
                int(event["code"]),
                float(event.get("duration_s", 0)),
                tail(_readable(buffer) if step.report == "go-json" else buffer),
                bool(event.get("timed_out")),
                bool(event.get("oom_killed")),
            )
    await emit({"type": "step_done", "result": {**asdict(result), "ok": result.ok}})
    return result, buffer


async def run_action(
    client: SandboxClient, sid: str, repo: Path, component: Component, action: Action, emit: Emit
) -> ActionResult:
    """build / test / lint a component. Stops at the first failing required step."""
    started = time.monotonic()
    exclude_from_git(repo)
    p = pack(component.pack)
    result = ActionResult(action, component.path, component.pack)
    reported: tuple[Step, str] | None = None
    for step in plan(repo, component, action):
        command, output = await run_step(client, sid, step, emit)
        result.steps.append(command)
        if step.report:
            if step.report == "go-json":
                saved = repo / component.path / REPORTS / "go-test.json"
                output = saved.read_text(encoding="utf-8", errors="replace") if saved.exists() else output
            result.report = p.read_report(repo, component, step, output)
            reported = (step, output)
            await emit({"type": "report", "report": result.report.as_dict()})
        elif reported is not None and result.report is not None and result.report.coverage is None:
            # a step after the tests may write the coverage (the C++ pack's instrumented build)
            result.report.coverage = p.read_report(repo, component, *reported).coverage
            if result.report.coverage is not None:
                await emit({"type": "report", "report": result.report.as_dict()})
        if not command.ok and not step.optional:
            break
    required = [s for s, st in zip(result.steps, plan(repo, component, action), strict=False) if not st.optional]
    result.ok = bool(result.steps) and all(s.ok for s in required) and (result.report is None or result.report.ok)
    if action == "test" and result.report is None and result.ok:
        result.error = "no test runner found for this component"
    result.duration_s = round(time.monotonic() - started, 2)
    return result


def run_spec(repo: Path, component: Component) -> RunSpec | None:
    return pack(component.pack).run_spec(repo, component)


# ── run helpers shared by every pack ─────────────────────────────────────────
_SAMPLE = re.compile(
    r"^(?P<stem>.+?)[._-](?:sample|example|dist|template)(?P<ext>\.(?:ya?ml|json|toml|ini|env|conf))?$"
)
CONFIG_EXTS = {".yaml", ".yml", ".json", ".toml", ".ini", ".env", ".conf", ""}


def sample_configs(repo: Path, component: Component) -> list[tuple[str, str]]:
    """Sample config files whose real file is missing (`config.sample.yaml` → `config.yaml`, `.env.example` →
    `.env`): projects document "copy the sample first"; the sandbox does that in the work copy. (sample, target)."""
    root = repo / component.path
    pairs = []
    for f in sorted(root.iterdir()) if root.is_dir() else []:
        m = _SAMPLE.match(f.name)
        if not f.is_file() or not m:
            continue
        target = m.group("stem") + (m.group("ext") or "")
        if Path(target).suffix not in CONFIG_EXTS or (root / target).exists():
            continue
        pairs.append((f.name, target))
    return pairs


def copy_samples(repo: Path, component: Component) -> list[str]:
    """Copy the missing configs into place and keep them out of git. Returns what was copied, for the log."""
    done = []
    root = repo / component.path
    for sample, target in sample_configs(repo, component):
        shutil.copyfile(root / sample, root / target)
        rel_target = f"{component.path}/{target}" if component.path != "." else target
        _exclude(repo, "/" + rel_target)
        done.append(f"{sample} → {target}")
    return done


def _exclude(work: Path, pattern: str) -> None:
    exclude = work / ".git" / "info" / "exclude"
    if exclude.parent.is_dir():
        text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if pattern not in text.split():
            exclude.write_text(text.rstrip("\n") + f"\n{pattern}\n", encoding="utf-8")


MIGRATION_DIRS = ("migrations", "db/migrations", "database/migrations", "sql/migrations")


def migrations(repo: Path, component: Component) -> list[Path]:
    """`*.up.sql` files (golang-migrate / migrate-style), in order, from the usual folders."""
    for base in dict.fromkeys([component.path, "."]):
        for folder in MIGRATION_DIRS:
            found = sorted((repo / base / folder).glob("*.up.sql"))
            if found:
                return found
    return []


_URI = re.compile(r"^[a-z][a-z0-9+.-]*://(?:[^@/\s]*@)?(?P<host>\[[^\]]+\]|[^:/?#\s]+)", re.IGNORECASE)
SAFE_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def production_like(env: dict[str, str], services: list[str]) -> list[str]:
    """Variables holding a connection string to a host Codewright didn't create (CODEWRIGHT.md Section 11: no
    production). The run is refused unless the user overrides it."""
    flagged = []
    allowed = SAFE_HOSTS | set(services)
    for key, value in env.items():
        m = _URI.match(value.strip())
        if not m or m.group(0).lower().startswith(("http://", "https://")):
            continue
        host = m.group("host").strip("[]").lower()
        if host not in allowed:
            flagged.append(f"{key} → {host}")
    return flagged
