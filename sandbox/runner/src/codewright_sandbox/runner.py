"""Sessions, jobs and previews: the only things the runner lets callers ask Docker for (ADR 0020).

- A **session** belongs to one workspace. It owns an internal Docker network (no route out; the egress gateway is
  attached as `egress`) and the project's sidecar services (Postgres, Redis...), reachable by their compose names.
- A **job** runs one command in a toolchain image with `/work` = the workspace's `work/` folder and streams its output.
- A **preview** keeps a process running: `web` (its port is forwarded to `127.0.0.1:<port>` by the gateway) or
  `terminal` (an interactive TTY the browser types into).

Every container: allowed image only, non-root (uid 10001), all capabilities dropped (sidecars keep the defaults
their entrypoints need), no setuid binaries, read-only root filesystem with tmpfs $HOME and /tmp, CPU/memory/PID and
time limits, no host network, no host paths (only the workspace volume's sub-folder and the cache volume).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import posixpath
import re
import secrets
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from codewright_sandbox.config import UID, Env, Limits, SandboxConfig
from codewright_sandbox.docker import Docker, DockerError

log = logging.getLogger(__name__)

LABEL = "codewright.sandbox"
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
WORKSPACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
PROXY = "http://egress:3128"
SCROLLBACK = 256_000


class SandboxError(RuntimeError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ── requests ─────────────────────────────────────────────────────────────────
class ServiceSpec(BaseModel):
    name: str  # the hostname the app uses (`postgres`, `redis`): the service's name in the project's compose file
    image: str
    env: dict[str, str] = {}

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not NAME.match(v):
            raise ValueError("service names are lower-case letters, digits, - and _")
        return v


class SessionSpec(BaseModel):
    workspace: str
    services: list[ServiceSpec] = Field(default=[], max_length=6)

    @field_validator("workspace")
    @classmethod
    def _workspace(cls, v: str) -> str:
        if not WORKSPACE.match(v):
            raise ValueError("invalid workspace id")
        return v


class ProcessSpec(BaseModel):
    toolchain: Literal["python", "go", "node", "cpp", "tools", "browser"]
    cmd: list[str] = Field(min_length=1, max_length=256)
    workdir: str = Field(default=".", validate_default=True)
    env: dict[str, str] = {}
    network: Literal["registry", "none"] = "registry"
    cpus: float | None = Field(default=None, gt=0)
    memory_mb: int | None = Field(default=None, ge=64)
    timeout_s: int | None = Field(default=None, ge=1)

    @field_validator("workdir")
    @classmethod
    def _workdir(cls, v: str) -> str:
        path = posixpath.normpath(posixpath.join("/work", v))
        if path != "/work" and not path.startswith("/work/"):
            raise ValueError("workdir must stay inside the workspace")
        return path

    @field_validator("env")
    @classmethod
    def _env(cls, v: dict[str, str]) -> dict[str, str]:
        if bad := [k for k in v if not ENV_KEY.match(k)]:
            raise ValueError(f"invalid environment variable names: {bad[:3]}")
        return v


class JobSpec(ProcessSpec):
    pass


class PreviewSpec(ProcessSpec):
    kind: Literal["web", "terminal"]
    port: int | None = Field(default=None, ge=1, le=65535)  # the port a web preview listens on in its container
    name: str = ""  # a label for the UI ("api", "web")
    # Share another preview's network (same `localhost`): a frontend dev server that proxies to localhost:<api>.
    share_network_of: str | None = None


class SqlSpec(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)


# ── state ────────────────────────────────────────────────────────────────────
class Output:
    """A process's output: a scrollback buffer plus live subscribers (reconnecting clients see the history)."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.subscribers: set[asyncio.Queue[bytes | None]] = set()
        self.exit_code: int | None = None
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buffer += data
        if len(self.buffer) > SCROLLBACK:
            del self.buffer[: len(self.buffer) - SCROLLBACK]
        for q in self.subscribers:
            q.put_nowait(data)

    def close(self, code: int | None) -> None:
        self.exit_code, self.closed = code, True
        for q in self.subscribers:
            q.put_nowait(None)

    async def follow(self) -> AsyncIterator[bytes]:
        q: asyncio.Queue[bytes | None] = asyncio.Queue()
        if self.buffer:
            q.put_nowait(bytes(self.buffer))
        if self.closed:
            q.put_nowait(None)
        else:
            self.subscribers.add(q)
        try:
            while (chunk := await q.get()) is not None:
                yield chunk
        finally:
            self.subscribers.discard(q)


@dataclass
class Preview:
    id: str
    session: str
    kind: str
    name: str
    container: str
    cmd: list[str]
    target_port: int | None = None
    host_port: int | None = None
    address: str | None = None  # a web preview's IP on its session network
    output: Output = field(default_factory=Output)
    writer: asyncio.StreamWriter | None = None
    tasks: list[asyncio.Task[Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session": self.session,
            "kind": self.kind,
            "name": self.name,
            "cmd": self.cmd,
            "port": self.target_port,
            "url": f"http://localhost:{self.host_port}/" if self.host_port else None,
            "running": not self.output.closed,
            "exit_code": self.output.exit_code,
            "started_at": self.started_at,
        }


@dataclass
class Session:
    id: str
    workspace: str
    network: str
    services: dict[str, str] = field(default_factory=dict)  # name → container id
    service_specs: dict[str, ServiceSpec] = field(default_factory=dict)
    previews: dict[str, Preview] = field(default_factory=dict)
    jobs: set[str] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)
    touched_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace": self.workspace,
            "services": sorted(self.services),
            "previews": [p.as_dict() for p in self.previews.values()],
            "created_at": self.created_at,
            "touched_at": self.touched_at,
        }


# ── runner ───────────────────────────────────────────────────────────────────
class Runner:
    def __init__(self, config: SandboxConfig, env: Env, docker: Docker) -> None:
        self.config = config
        self.env = env
        self.docker = docker
        self.sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task[None] | None = None

    # lifecycle
    async def start(self) -> None:
        await self.cleanup_orphans()
        self._write_routes()
        self._reaper = asyncio.create_task(self._reap_forever())

    async def stop(self) -> None:
        if self._reaper:
            self._reaper.cancel()
        for sid in list(self.sessions):
            await self.delete_session(sid)

    async def cleanup_orphans(self) -> None:
        """Containers and networks left by an earlier runner (sessions live in memory, so they can't be resumed)."""
        for c in await self.docker.containers(f"{LABEL}=1"):
            await self.docker.remove(c["Id"])
        gateway = await self._gateway()
        for n in await self.docker.networks(f"{LABEL}=1"):
            if gateway:
                with contextlib.suppress(DockerError):
                    await self.docker.disconnect(n["Id"], gateway)
            await self.docker.remove_network(n["Id"])

    async def _reap_forever(self) -> None:
        while True:
            await asyncio.sleep(30)
            now = time.time()
            for s in list(self.sessions.values()):
                if now - s.touched_at > self.config.session_ttl_s and not s.jobs:
                    log.info("session %s idle for %ds: removing", s.id, now - s.touched_at)
                    with contextlib.suppress(Exception):
                        await self.delete_session(s.id)

    async def health(self) -> dict[str, Any]:
        ok = await self.docker.ping()
        images = {k: ok and await self.docker.image_exists(v) for k, v in self.config.images.items()}
        return {"docker": ok, "gateway": bool(ok and await self._gateway()), "images": images}

    def _labels(self, sid: str, role: str) -> dict[str, str]:
        return {LABEL: "1", "codewright.session": sid, "codewright.role": role}

    async def _gateway(self) -> str | None:
        found = await self.docker.containers(f"com.docker.compose.service={self.env.gateway_service}")
        for c in found:
            if c.get("Labels", {}).get("com.docker.compose.project") == self.env.compose_project and (
                c.get("State") == "running"
            ):
                return str(c["Id"])
        return None

    def session(self, sid: str) -> Session:
        s = self.sessions.get(sid)
        if s is None:
            raise SandboxError("no such session", 404)
        s.touched_at = time.time()
        return s

    # sessions
    async def create_session(self, spec: SessionSpec) -> Session:
        async with self._lock:
            if len(self.sessions) >= self.config.max_sessions:
                raise SandboxError(f"at most {self.config.max_sessions} sandbox sessions at a time", 429)
            for svc in spec.services:
                if self.config.service_kind(svc.image) is None:
                    allowed = sorted(i for k in self.config.services.values() for i in k.images)
                    raise SandboxError(f"image {svc.image!r} isn't an allowed service (allowed: {', '.join(allowed)})")
            gateway = await self._gateway()
            if gateway is None:
                raise SandboxError("the sandbox gateway isn't running", 503)
            sid = secrets.token_hex(6)
            name = f"{self.env.prefix}-{sid}"
            network = await self.docker.create_network(name, self._labels(sid, "network"))
            session = Session(id=sid, workspace=spec.workspace, network=network)
            self.sessions[sid] = session
        try:
            await self.docker.connect(network, gateway, ["egress"])
            for svc in spec.services:
                session.services[svc.name] = await self._start_service(session, svc)
                session.service_specs[svc.name] = svc
            await asyncio.gather(*(self._wait_ready(session, svc) for svc in spec.services))
        except BaseException:
            await self.delete_session(sid)
            raise
        return session

    async def add_services(self, sid: str, services: list[ServiceSpec]) -> Session:
        """Start more sidecars in a session (the ones it already has are kept)."""
        session = self.session(sid)
        new = [svc for svc in services if svc.name not in session.services]
        for svc in new:
            if self.config.service_kind(svc.image) is None:
                raise SandboxError(f"image {svc.image!r} isn't an allowed service")
        if len(session.services) + len(new) > 6:
            raise SandboxError("at most 6 services per session")
        for svc in new:
            session.services[svc.name] = await self._start_service(session, svc)
            session.service_specs[svc.name] = svc
        await asyncio.gather(*(self._wait_ready(session, svc) for svc in new))
        return session

    async def run_sql(self, sid: str, name: str, sql: str) -> dict[str, Any]:
        """Run SQL in a sidecar (migrations), with the sidecar's own client; its output and exit code."""
        session = self.session(sid)
        svc = session.service_specs.get(name)
        if svc is None:
            raise SandboxError(f"no service {name!r} in this session", 404)
        kind = self.config.services[self.config.service_kind(svc.image) or ""]
        if not kind.sql:
            raise SandboxError(f"service {name!r} doesn't take SQL")

        def fill(arg: str) -> str:
            if arg == "{sql}":
                return sql
            return re.sub(r"\{(\w+):([^}]*)\}", lambda m: svc.env.get(m.group(1)) or m.group(2), arg)

        code, output = await self.docker.exec(session.services[name], [fill(a) for a in kind.sql], timeout=120)
        return {"code": code, "output": output[-20_000:]}

    async def delete_session(self, sid: str) -> None:
        session = self.sessions.pop(sid, None)
        if session is None:
            return
        for p in list(session.previews.values()):
            await self._remove_preview(session, p)
        for c in await self.docker.containers(f"codewright.session={sid}"):
            await self.docker.remove(c["Id"])
        if gateway := await self._gateway():
            with contextlib.suppress(DockerError):
                await self.docker.disconnect(session.network, gateway)
        await self.docker.remove_network(session.network)
        self._write_routes()

    async def _start_service(self, session: Session, svc: ServiceSpec) -> str:
        kind = self.config.services[self.config.service_kind(svc.image) or ""]
        if not await self.docker.image_exists(svc.image):
            log.info("pulling %s", svc.image)
            await self.docker.pull(svc.image)
        spec = {
            "Image": svc.image,
            "Env": [f"{k}={v}" for k, v in svc.env.items() if ENV_KEY.match(k)],
            "Labels": self._labels(session.id, "service"),
            "HostConfig": {
                "NetworkMode": session.network,
                "Memory": kind.memory_mb * 2**20,
                "MemorySwap": kind.memory_mb * 2**20,
                "NanoCpus": int(1e9),
                "PidsLimit": 256,
                "SecurityOpt": self._security_opt(),
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "5m"}},
            },
            "NetworkingConfig": {"EndpointsConfig": {session.network: {"Aliases": [svc.name]}}},
        }
        container = await self.docker.create(f"{self.env.prefix}-{session.id}-{svc.name}", spec)
        await self.docker.start(container)
        return container

    async def _wait_ready(self, session: Session, svc: ServiceSpec, timeout: float = 90) -> None:
        kind = self.config.services[self.config.service_kind(svc.image) or ""]
        if not kind.ready:
            return
        deadline = time.monotonic() + timeout
        container = session.services[svc.name]
        while time.monotonic() < deadline:
            with contextlib.suppress(DockerError, TimeoutError):
                if (await self.docker.exec(container, kind.ready))[0] == 0:
                    return
            state = (await self.docker.inspect(container))["State"]
            if not state.get("Running"):
                raise SandboxError(f"service {svc.name} stopped (exit code {state.get('ExitCode')})", 502)
            await asyncio.sleep(1)
        raise SandboxError(f"service {svc.name} wasn't ready after {timeout:.0f}s", 504)

    # containers
    def _security_opt(self) -> list[str]:
        # Off by default: on some Docker hosts it makes every exec fail with EPERM (ADR 0020). The toolchain images
        # have no setuid/setgid binaries and all capabilities are dropped, so nothing can gain privileges anyway.
        return ["no-new-privileges"] if self.config.no_new_privileges else []

    def _mounts(self, workspace: str, toolchain: str) -> list[dict[str, Any]]:
        mounts: list[dict[str, Any]] = [
            {
                "Type": "volume",
                "Source": self.env.workspaces_volume,
                "Target": "/work",
                "VolumeOptions": {"Subpath": f"{workspace}/work", "NoCopy": True},
            }
        ]
        for target, sub in self.config.caches.get(toolchain, {}).items():
            path = self.env.cache_dir / sub
            path.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                for p in (path, *path.parents):
                    if p == self.env.cache_dir.parent:
                        break
                    os.chown(p, UID, UID)
            mounts.append(
                {
                    "Type": "volume",
                    "Source": self.env.cache_volume,
                    "Target": target,
                    "VolumeOptions": {"Subpath": sub, "NoCopy": True},
                }
            )
        return mounts

    def _process_spec(
        self, session: Session, p: ProcessSpec, limits: Limits, role: str, *, tty: bool = False
    ) -> dict[str, Any]:
        env = {**p.env, "HOME": "/home/sandbox", "CI": "true"}
        if not tty:
            env.setdefault("NO_COLOR", "1")
        else:
            env.setdefault("TERM", "xterm-256color")
        if p.network == "registry":
            no_proxy = ",".join(["localhost", "127.0.0.1", *session.services])
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                env[key] = PROXY
            env["NO_PROXY"] = env["no_proxy"] = no_proxy
        mb = 2**20
        host: dict[str, Any] = {
            "Mounts": self._mounts(session.workspace, p.toolchain),
            "NetworkMode": session.network if p.network == "registry" else "none",
            "NanoCpus": int(limits.cpus * 1e9),
            "Memory": limits.memory_mb * mb,
            "MemorySwap": limits.memory_mb * mb,
            "PidsLimit": limits.pids,
            "CapDrop": ["ALL"],
            "SecurityOpt": self._security_opt(),
            "ReadonlyRootfs": True,
            "Tmpfs": {  # paths inside the container
                "/tmp": f"rw,exec,nosuid,size={self.config.limits.tmp_mb}m,mode=1777",
                "/home/sandbox": f"rw,exec,nosuid,size={self.config.limits.home_mb}m,uid={UID},gid={UID},mode=0755",
            },
            "LogConfig": {"Type": "json-file", "Config": {"max-size": "10m"}},
        }
        spec: dict[str, Any] = {
            "Image": self.config.images[p.toolchain],
            "Cmd": p.cmd,
            "Env": [f"{k}={v}" for k, v in env.items()],
            "WorkingDir": p.workdir,
            "User": f"{UID}:{UID}",
            "Labels": self._labels(session.id, role),
            "HostConfig": host,
        }
        if tty:
            spec |= {"Tty": True, "OpenStdin": True, "AttachStdin": True, "AttachStdout": True, "AttachStderr": True}
        if p.network == "registry":
            spec["NetworkingConfig"] = {"EndpointsConfig": {session.network: {}}}
        return spec

    # jobs
    async def job(self, sid: str, spec: JobSpec) -> AsyncIterator[dict[str, Any]]:
        """Run a command to completion; yields `output` events, then one `exit` event."""
        session = self.session(sid)
        limits = self.config.clamp(spec.cpus, spec.memory_mb, spec.timeout_s)
        name = f"{self.env.prefix}-{sid}-job-{secrets.token_hex(3)}"
        container = await self.docker.create(name, self._process_spec(session, spec, limits, "job"))
        session.jobs.add(container)
        started = time.monotonic()
        timed_out = False

        async def watchdog() -> None:
            nonlocal timed_out
            await asyncio.sleep(limits.timeout_s)
            timed_out = True
            await self.docker.kill(container)

        dog: asyncio.Task[None] | None = None
        try:
            await self.docker.start(container)
            dog = asyncio.create_task(watchdog())
            yield {"type": "start", "cmd": spec.cmd, "workdir": spec.workdir, "limits": limits.model_dump()}
            sent, cut = 0, False
            async for stream, chunk in self.docker.logs(container):
                session.touched_at = time.time()
                if cut:
                    continue
                if sent + len(chunk) > self.config.limits.output_bytes:
                    cut = True
                    yield {"type": "truncated", "after_bytes": sent}
                    continue
                sent += len(chunk)
                yield {"type": "output", "stream": stream, "text": chunk.decode(errors="replace")}
            code = await self.docker.wait(container)
            state = (await self.docker.inspect(container))["State"]
            yield {
                "type": "exit",
                "code": code,
                "timed_out": timed_out,
                "oom_killed": bool(state.get("OOMKilled")),
                "duration_s": round(time.monotonic() - started, 2),
            }
        finally:
            if dog:
                dog.cancel()
            session.jobs.discard(container)
            await self.docker.remove(container)

    # previews
    def _free_port(self) -> int:
        used = {p.host_port for s in self.sessions.values() for p in s.previews.values()}
        first, count = self.config.previews.first_port, self.config.previews.count
        for port in range(first, first + count):
            if port not in used:
                return port
        raise SandboxError(f"all {count} preview ports are in use; stop a preview first", 429)

    def _write_routes(self) -> None:
        """Preview routes for the gateway: host port → container address on its session network."""
        routes: dict[str, str] = {}
        for s in self.sessions.values():
            for p in s.previews.values():
                if p.host_port and p.target_port and p.address:
                    routes[str(p.host_port)] = f"{p.address}:{p.target_port}"
        self.env.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.env.state_dir / "routes.json.tmp"
        tmp.write_text(json.dumps(routes), encoding="utf-8")
        tmp.replace(self.env.state_dir / "routes.json")

    async def start_preview(self, sid: str, spec: PreviewSpec) -> Preview:
        session = self.session(sid)
        if spec.kind == "web" and (spec.port is None or spec.network != "registry"):
            raise SandboxError("a web preview needs `port` and the session network")
        limits = self.config.clamp(spec.cpus, spec.memory_mb, self.config.limits.max.timeout_s)
        pid = secrets.token_hex(4)
        name = f"{self.env.prefix}-{sid}-preview-{pid}"
        container_spec = self._process_spec(session, spec, limits, "preview", tty=spec.kind == "terminal")
        partner = session.previews.get(spec.share_network_of or "") if spec.share_network_of else None
        if spec.share_network_of and (partner is None or partner.address is None):
            raise SandboxError("share_network_of must name a running web preview of this session")
        if partner is not None:
            container_spec["HostConfig"]["NetworkMode"] = f"container:{partner.container}"
            container_spec.pop("NetworkingConfig", None)
        elif spec.kind == "web":
            container_spec["NetworkingConfig"] = {"EndpointsConfig": {session.network: {"Aliases": [spec.name or pid]}}}
        container = await self.docker.create(name, container_spec)
        preview = Preview(
            id=pid, session=sid, kind=spec.kind, name=spec.name or spec.kind, container=container, cmd=spec.cmd
        )
        session.previews[pid] = preview
        try:
            if spec.kind == "terminal":
                reader, preview.writer = await self.docker.attach(container)
                await self.docker.start(container)
                preview.tasks.append(asyncio.create_task(self._pump_tty(preview, reader)))
            else:
                await self.docker.start(container)
                preview.tasks.append(asyncio.create_task(self._pump_logs(preview)))
                if partner is not None:
                    preview.address = partner.address
                else:
                    info = await self.docker.inspect(container)
                    preview.address = info["NetworkSettings"]["Networks"][self._network_name(session)]["IPAddress"]
                preview.target_port = spec.port
                preview.host_port = self._free_port()
                self._write_routes()
            preview.tasks.append(asyncio.create_task(self._watch_exit(preview)))
        except BaseException:
            await self._remove_preview(session, preview)
            raise
        return preview

    def _network_name(self, session: Session) -> str:
        return f"{self.env.prefix}-{session.id}"

    async def _pump_tty(self, preview: Preview, reader: asyncio.StreamReader) -> None:
        while chunk := await reader.read(65536):
            preview.output.write(chunk)

    async def _pump_logs(self, preview: Preview) -> None:
        with contextlib.suppress(DockerError):
            async for _, chunk in self.docker.logs(preview.container):
                preview.output.write(chunk)

    async def _watch_exit(self, preview: Preview) -> None:
        code: int | None = None
        with contextlib.suppress(DockerError):
            code = await self.docker.wait(preview.container)
        await asyncio.sleep(0.2)  # let the pumps drain the last output
        preview.output.close(code)

    def preview(self, sid: str, pid: str) -> Preview:
        p = self.session(sid).previews.get(pid)
        if p is None:
            raise SandboxError("no such preview", 404)
        return p

    async def send_input(self, sid: str, pid: str, data: str) -> None:
        p = self.preview(sid, pid)
        if p.writer is None or p.output.closed:
            raise SandboxError("this preview doesn't take input", 409)
        p.writer.write(data.encode())
        await p.writer.drain()

    async def resize(self, sid: str, pid: str, rows: int, cols: int) -> None:
        p = self.preview(sid, pid)
        if p.kind == "terminal" and not p.output.closed:
            await self.docker.resize(p.container, rows, cols)

    async def stop_preview(self, sid: str, pid: str) -> None:
        session = self.session(sid)
        await self._remove_preview(session, self.preview(sid, pid))

    async def _remove_preview(self, session: Session, preview: Preview) -> None:
        session.previews.pop(preview.id, None)
        for t in preview.tasks:
            t.cancel()
        if preview.writer is not None:
            preview.writer.close()
        await self.docker.remove(preview.container)
        if not preview.output.closed:
            preview.output.close(None)
        self._write_routes()
