"""The sandbox runner and gateway without Docker: what the runner asks Docker for (limits, mounts, network, user),
what it refuses, and the gateway's allowlist, address checks and preview routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from codewright_sandbox.config import Env, SandboxConfig
from codewright_sandbox.gateway import Gateway, host_allowed, public_address
from codewright_sandbox.runner import JobSpec, Output, PreviewSpec, Runner, SandboxError, ServiceSpec, SessionSpec

CONFIG = SandboxConfig.load(Path(__file__).resolve().parents[3] / "config" / "sandbox.yaml")


class FakeDocker:
    """Records what the runner asks for; containers 'run' instantly and print one line."""

    def __init__(self) -> None:
        self.created: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []  # every spec asked for, also of containers removed since
        self.removed: list[str] = []
        self.nets: dict[str, dict[str, Any]] = {}
        self.connected: list[tuple[str, str, list[str]]] = []
        self.exit_code = 0
        self.exec_calls: list[list[str]] = []

    async def ping(self) -> bool:
        return True

    async def image_exists(self, ref: str) -> bool:
        return True

    async def pull(self, ref: str) -> None:
        raise AssertionError("no pulls in tests")

    async def containers(self, label: str) -> list[dict[str, Any]]:
        if label.startswith("com.docker.compose.service="):
            return [{"Id": "gw", "State": "running", "Labels": {"com.docker.compose.project": "codewright"}}]
        key, _, value = label.partition("=")
        return [{"Id": cid} for cid, spec in self.created.items() if spec.get("Labels", {}).get(key) == value]

    async def networks(self, label: str) -> list[dict[str, Any]]:
        return []

    async def create_network(self, name: str, labels: dict[str, str], *, internal: bool = True) -> str:
        self.nets[name] = {"internal": internal, "labels": labels}
        return name

    async def connect(self, network: str, container: str, aliases: list[str]) -> None:
        self.connected.append((network, container, aliases))

    async def disconnect(self, network: str, container: str) -> None:
        pass

    async def remove_network(self, network: str) -> None:
        self.nets.pop(network, None)

    async def create(self, name: str, spec: dict[str, Any]) -> str:
        self.created[name] = spec
        self.history.append(spec)
        return name

    async def start(self, container: str) -> None:
        pass

    async def inspect(self, container: str) -> dict[str, Any]:
        net = self.created[container]["HostConfig"]["NetworkMode"]
        return {
            "State": {"Running": True, "OOMKilled": False},
            "NetworkSettings": {"Networks": {net: {"IPAddress": "10.9.0.5"}}},
        }

    async def wait(self, container: str) -> int:
        return self.exit_code

    async def kill(self, container: str) -> None:
        pass

    async def remove(self, container: str) -> None:
        self.removed.append(container)
        self.created.pop(container, None)

    async def logs(self, container: str, *, follow: bool = True) -> AsyncIterator[tuple[str, bytes]]:
        yield "stdout", b"hello\n"

    async def exec(self, container: str, cmd: list[str], timeout: float = 10) -> tuple[int, str]:
        self.exec_calls.append(cmd)
        return 0, "ok"


@pytest.fixture
def runner(tmp_path: Path) -> tuple[Runner, FakeDocker]:
    docker = FakeDocker()
    env = Env(cache_dir=tmp_path / "cache", state_dir=tmp_path / "state")
    return Runner(CONFIG, env, docker), docker  # type: ignore[arg-type]


async def test_job_container_is_locked_down(runner: tuple[Runner, FakeDocker]) -> None:
    r, docker = runner
    session = await r.create_session(SessionSpec(workspace="proj-1"))
    events = [e async for e in r.job(session.id, JobSpec(toolchain="go", cmd=["go", "test", "./..."], workdir="svc"))]
    assert [e["type"] for e in events] == ["start", "output", "exit"]
    assert events[-1]["code"] == 0
    assert not [n for n in docker.created if "-job-" in n], "the job container is removed afterwards"
    spec = next(s for s in docker.history if s["Cmd"] == ["go", "test", "./..."])
    host = spec["HostConfig"]
    assert spec["Image"] == "codewright-sandbox-go:dev"
    assert spec["User"] == "10001:10001"
    assert spec["WorkingDir"] == "/work/svc"
    assert host["CapDrop"] == ["ALL"] and host["ReadonlyRootfs"] is True
    assert host["NetworkMode"] == session.network and "Privileged" not in host
    assert host["Memory"] == 2048 * 2**20 and host["NanoCpus"] == int(2e9) and host["PidsLimit"] == 512
    mounts = host["Mounts"]
    assert mounts[0] == {
        "Type": "volume",
        "Source": "codewright_workspaces",
        "Target": "/work",
        "VolumeOptions": {"Subpath": "proj-1/work", "NoCopy": True},
    }
    assert all(m["Type"] == "volume" for m in mounts), "never a host path"
    env = dict(e.split("=", 1) for e in spec["Env"])
    assert env["HTTPS_PROXY"] == "http://egress:3128"
    assert docker.nets[session.network]["internal"] is True
    assert ("gw" in {c for _, c, _ in docker.connected}) and docker.connected[0][2] == ["egress"]


async def test_offline_jobs_and_limits_are_capped(runner: tuple[Runner, FakeDocker]) -> None:
    r, docker = runner
    session = await r.create_session(SessionSpec(workspace="p"))
    spec = JobSpec(toolchain="node", cmd=["npm", "test"], network="none", cpus=64, memory_mb=10**6, timeout_s=10**6)
    [e async for e in r.job(session.id, spec)]
    created = docker.history[-1]
    host = created["HostConfig"]
    assert host["NetworkMode"] == "none" and "NetworkingConfig" not in created
    assert not any(e.startswith("HTTPS_PROXY=") for e in created["Env"])
    assert host["NanoCpus"] == int(4e9) and host["Memory"] == 4096 * 2**20  # the max, not what was asked


def test_workdir_cannot_leave_the_workspace() -> None:
    with pytest.raises(ValidationError):
        JobSpec(toolchain="go", cmd=["ls"], workdir="../../etc")
    with pytest.raises(ValidationError):
        SessionSpec(workspace="../other")
    with pytest.raises(ValidationError):
        JobSpec(toolchain="rust", cmd=["cargo"])
    assert JobSpec(toolchain="go", cmd=["ls"]).workdir == "/work"


async def test_only_allowed_service_images(runner: tuple[Runner, FakeDocker]) -> None:
    r, docker = runner
    with pytest.raises(SandboxError, match="isn't an allowed service"):
        await r.create_session(SessionSpec(workspace="p", services=[ServiceSpec(name="x", image="alpine:3")]))
    session = await r.create_session(
        SessionSpec(workspace="p", services=[ServiceSpec(name="db", image="postgres:16-alpine", env={"A": "1"})])
    )
    spec = docker.history[-1]
    assert spec["NetworkingConfig"]["EndpointsConfig"][session.network]["Aliases"] == ["db"]
    assert spec["HostConfig"]["Memory"] == 512 * 2**20
    assert docker.exec_calls[0][0] == "pg_isready"  # waited until ready


async def test_sql_uses_the_services_own_env(runner: tuple[Runner, FakeDocker]) -> None:
    r, docker = runner
    svc = ServiceSpec(name="db", image="postgres:16", env={"POSTGRES_USER": "shop"})
    session = await r.create_session(SessionSpec(workspace="p", services=[svc]))
    assert (await r.run_sql(session.id, "db", "select 1"))["code"] == 0
    assert docker.exec_calls[-1] == ["psql", "-v", "ON_ERROR_STOP=1", "-U", "shop", "-d", "postgres", "-c", "select 1"]
    with pytest.raises(SandboxError):
        await r.run_sql(session.id, "nope", "select 1")


async def test_session_limit_and_cleanup(runner: tuple[Runner, FakeDocker]) -> None:
    r, docker = runner
    sessions = [await r.create_session(SessionSpec(workspace=f"p{i}")) for i in range(CONFIG.max_sessions)]
    with pytest.raises(SandboxError) as e:
        await r.create_session(SessionSpec(workspace="one-more"))
    assert e.value.status == 429
    await r.delete_session(sessions[0].id)
    assert sessions[0].network not in docker.nets


async def test_web_preview_routes(runner: tuple[Runner, FakeDocker], tmp_path: Path) -> None:
    r, docker = runner
    session = await r.create_session(SessionSpec(workspace="p"))
    api = await r.start_preview(session.id, PreviewSpec(kind="web", toolchain="go", cmd=["./app"], port=8080))
    assert api.host_port == CONFIG.previews.first_port and api.address == "10.9.0.5"
    routes = json.loads((tmp_path / "state" / "routes.json").read_text())
    assert routes == {str(api.host_port): "10.9.0.5:8080"}
    web = await r.start_preview(
        session.id,
        PreviewSpec(kind="web", toolchain="node", cmd=["vite"], port=5173, share_network_of=api.id),
    )
    assert docker.history[-1]["HostConfig"]["NetworkMode"] == f"container:{api.container}"
    assert web.host_port == CONFIG.previews.first_port + 1
    await r.stop_preview(session.id, api.id)
    assert str(api.host_port) not in json.loads((tmp_path / "state" / "routes.json").read_text())
    with pytest.raises(SandboxError):
        await r.start_preview(session.id, PreviewSpec(kind="web", toolchain="node", cmd=["x"]))  # no port


async def test_output_scrollback_then_live() -> None:
    out = Output()
    out.write(b"before ")
    received: list[bytes] = []

    async def reader() -> None:
        async for chunk in out.follow():
            received.append(chunk)

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)
    out.write(b"after")
    out.close(0)
    await asyncio.wait_for(task, 1)
    assert b"".join(received) == b"before after" and out.exit_code == 0


# ── gateway ──────────────────────────────────────────────────────────────────
def test_allowlist_is_a_suffix_match() -> None:
    allow = CONFIG.egress.allow
    assert host_allowed("registry.npmjs.org", allow) and host_allowed("PyPI.org.", allow)
    assert not host_allowed("evil-pypi.org", allow)
    assert not host_allowed("pypi.org.evil.com", allow)
    assert not host_allowed("api", allow)


@pytest.mark.parametrize(
    ("ip", "public"),
    [("151.101.0.223", True), ("10.0.0.1", False), ("172.23.0.2", False), ("127.0.0.1", False),
     ("169.254.169.254", False), ("::1", False), ("fd00::1", False), ("2a00:1450:4018:80c::2011", True)],
)  # fmt: skip
def test_only_public_addresses(ip: str, public: bool) -> None:
    assert public_address(ip) is public


async def _ask(gateway: Gateway, request: bytes) -> bytes:
    server = await asyncio.start_server(gateway.handle_proxy, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    answer = await asyncio.wait_for(reader.read(4096), 5)
    writer.close()
    server.close()
    return answer


async def test_proxy_refuses_hosts_outside_the_allowlist(tmp_path: Path) -> None:
    gateway = Gateway(CONFIG, tmp_path)
    answer = await _ask(gateway, b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 403") and b"isn't an allowed package registry" in answer
    answer = await _ask(gateway, b"GET http://api:8000/api/health HTTP/1.1\r\nHost: api\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 403")


async def test_proxy_refuses_allowed_names_that_resolve_privately(tmp_path: Path) -> None:
    config = CONFIG.model_copy(update={"egress": CONFIG.egress.model_copy(update={"allow": ["localhost"]})})
    answer = await _ask(Gateway(config, tmp_path), b"CONNECT localhost:443 HTTP/1.1\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 403") and b"non-public" in answer


async def test_proxy_refuses_other_ports(tmp_path: Path) -> None:
    answer = await _ask(Gateway(CONFIG, tmp_path), b"CONNECT pypi.org:22 HTTP/1.1\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 403") and b"only ports 80 and 443" in answer


def test_preview_routes_are_read_per_connection(tmp_path: Path) -> None:
    gateway = Gateway(CONFIG, tmp_path)
    assert gateway.route(41000) is None
    (tmp_path / "routes.json").write_text(json.dumps({"41000": "10.0.0.7:5173"}))
    assert gateway.route(41000) == ("10.0.0.7", 5173)
