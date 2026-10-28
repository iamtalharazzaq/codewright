"""A small async client for the Docker Engine API over its Unix socket (only the calls the runner needs).

Docker's own SDK is synchronous and hides the request bodies; the runner wants to see exactly what it asks Docker
for (every container's mounts, limits and network), so it speaks the documented Engine API directly:
https://docs.docker.com/reference/api/engine/
"""

from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urlencode

import httpx

API_VERSION = "v1.47"  # volume subpaths need 1.45+


class DockerError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Docker {status}: {message}")
        self.status = status


class Docker:
    def __init__(self, socket: str = "/var/run/docker.sock") -> None:
        self.socket = socket
        self.http = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=socket),
            base_url=f"http://docker/{API_VERSION}",
            timeout=httpx.Timeout(60, read=None),
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, path: str, *, params: dict[str, Any] | None = None, body: Any = None) -> Any:
        response = await self.http.request(method, path, params=params, json=body)
        if response.status_code >= 400:
            try:
                message = response.json().get("message", response.text)
            except ValueError:
                message = response.text
            raise DockerError(response.status_code, message)
        if not response.content:
            return None
        return response.json() if "json" in response.headers.get("content-type", "") else response.text

    # ── system / images ──────────────────────────────────────────────────────
    async def ping(self) -> bool:
        try:
            return (await self.http.get("/_ping")).status_code == 200
        except httpx.HTTPError:
            return False

    async def image_exists(self, ref: str) -> bool:
        try:
            await self._call("GET", f"/images/{quote(ref, safe='')}/json")
        except DockerError as e:
            if e.status == 404:
                return False
            raise
        return True

    async def pull(self, ref: str) -> None:
        name, _, tag = ref.rpartition(":") if ":" in ref.rsplit("/", 1)[-1] else (ref, "", "latest")
        async with self.http.stream("POST", "/images/create", params={"fromImage": name, "tag": tag}) as response:
            if response.status_code >= 400:
                raise DockerError(response.status_code, (await response.aread()).decode(errors="replace"))
            async for line in response.aiter_lines():
                if line.strip() and "error" in (event := json.loads(line)):
                    raise DockerError(500, str(event["error"]))

    # ── networks ─────────────────────────────────────────────────────────────
    async def create_network(self, name: str, labels: dict[str, str], *, internal: bool = True) -> str:
        body = {"Name": name, "Driver": "bridge", "Internal": internal, "Labels": labels, "CheckDuplicate": True}
        result = await self._call("POST", "/networks/create", body=body)
        return str(result["Id"])

    async def connect(self, network: str, container: str, aliases: list[str]) -> None:
        body = {"Container": container, "EndpointConfig": {"Aliases": aliases}}
        await self._call("POST", f"/networks/{network}/connect", body=body)

    async def disconnect(self, network: str, container: str) -> None:
        await self._call("POST", f"/networks/{network}/disconnect", body={"Container": container, "Force": True})

    async def remove_network(self, network: str) -> None:
        try:
            await self._call("DELETE", f"/networks/{network}")
        except DockerError as e:
            if e.status != 404:
                raise

    async def networks(self, label: str) -> list[dict[str, Any]]:
        filters = json.dumps({"label": [label]})
        result: list[dict[str, Any]] = await self._call("GET", "/networks", params={"filters": filters})
        return result

    # ── containers ───────────────────────────────────────────────────────────
    async def containers(self, label: str) -> list[dict[str, Any]]:
        filters = json.dumps({"label": [label]})
        result: list[dict[str, Any]] = await self._call(
            "GET", "/containers/json", params={"all": "1", "filters": filters}
        )
        return result

    async def create(self, name: str, spec: dict[str, Any]) -> str:
        result = await self._call("POST", "/containers/create", params={"name": name}, body=spec)
        return str(result["Id"])

    async def start(self, container: str) -> None:
        await self._call("POST", f"/containers/{container}/start")

    async def inspect(self, container: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._call("GET", f"/containers/{container}/json")
        return result

    async def wait(self, container: str) -> int:
        result = await self._call("POST", f"/containers/{container}/wait")
        return int(result["StatusCode"])

    async def kill(self, container: str) -> None:
        try:
            await self._call("POST", f"/containers/{container}/kill")
        except DockerError as e:
            if e.status not in (404, 409):  # gone or not running
                raise

    async def remove(self, container: str) -> None:
        try:
            await self._call("DELETE", f"/containers/{container}", params={"force": "1", "v": "1"})
        except DockerError as e:
            if e.status != 404:
                raise

    async def resize(self, container: str, rows: int, cols: int) -> None:
        await self._call("POST", f"/containers/{container}/resize", params={"h": rows, "w": cols})

    async def logs(self, container: str, *, follow: bool = True) -> AsyncIterator[tuple[str, bytes]]:
        """(stream, chunk) pairs of a non-TTY container's output, demultiplexed."""
        params = {"follow": "1" if follow else "0", "stdout": "1", "stderr": "1"}
        async with self.http.stream("GET", f"/containers/{container}/logs", params=params) as response:
            if response.status_code >= 400:
                raise DockerError(response.status_code, (await response.aread()).decode(errors="replace"))
            buffer = b""
            async for data in response.aiter_raw():
                buffer += data
                while len(buffer) >= 8:
                    kind, size = buffer[0], struct.unpack(">I", buffer[4:8])[0]
                    if len(buffer) < 8 + size:
                        break
                    yield ("stderr" if kind == 2 else "stdout"), buffer[8 : 8 + size]
                    buffer = buffer[8 + size :]

    async def exec(self, container: str, cmd: list[str], timeout: float = 10) -> tuple[int, str]:
        """Run a command in a running container: (exit code, output)."""
        created = await self._call(
            "POST", f"/containers/{container}/exec", body={"Cmd": cmd, "AttachStdout": True, "AttachStderr": True}
        )
        exec_id = created["Id"]
        out = bytearray()
        async with asyncio.timeout(timeout):
            async with self.http.stream("POST", f"/exec/{exec_id}/start", json={"Detach": False}) as response:
                buffer = b""
                async for data in response.aiter_raw():
                    buffer += data
                    while len(buffer) >= 8:
                        size = struct.unpack(">I", buffer[4:8])[0]
                        if len(buffer) < 8 + size:
                            break
                        out += buffer[8 : 8 + size]
                        buffer = buffer[8 + size :]
        info = await self._call("GET", f"/exec/{exec_id}/json")
        code = info.get("ExitCode")
        return (-1 if code is None else int(code)), out.decode(errors="replace")

    async def attach(self, container: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """A raw two-way stream to a TTY container's terminal (the HTTP connection is hijacked, as `docker attach`
        does). Attach before `start` so no output is missed."""
        reader, writer = await asyncio.open_unix_connection(self.socket)
        query = urlencode({"stream": 1, "stdin": 1, "stdout": 1, "stderr": 1, "logs": 1})
        writer.write(
            (
                f"POST /{API_VERSION}/containers/{container}/attach?{query} HTTP/1.1\r\n"
                "Host: docker\r\nConnection: Upgrade\r\nUpgrade: tcp\r\nContent-Length: 0\r\n\r\n"
            ).encode()
        )
        await writer.drain()
        status = await reader.readline()
        if b" 101 " not in status and b" 200 " not in status:
            writer.close()
            raise DockerError(500, f"attach failed: {status.decode(errors='replace').strip()}")
        while await reader.readline() not in (b"\r\n", b""):
            pass  # response headers
        return reader, writer
