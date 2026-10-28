"""Client for the sandbox runner (ADR 0020). The API never talks to Docker; it asks the runner, which only runs
toolchain images on a project's `work/` folder, with limits and registry-only network."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

DEFAULT_URL = "http://sandbox-runner:8200"


class SandboxUnavailable(RuntimeError):
    pass


class SandboxRequestError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status


class SandboxClient:
    def __init__(self, url: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.url = (url or os.environ.get("SANDBOX_URL") or DEFAULT_URL).rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.url, timeout=httpx.Timeout(30, read=None), transport=transport)

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, path: str, body: Any = None) -> Any:
        try:
            response = await self.http.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise SandboxUnavailable(
                f"The sandbox runner isn't reachable at {self.url} ({e.__class__.__name__})."
            ) from e
        if response.status_code >= 400:
            raise SandboxRequestError(response.status_code, _detail(response))
        return response.json() if response.content else None

    async def health(self) -> dict[str, Any]:
        result: dict[str, Any] = await self._call("GET", "/health")
        return result

    async def create_session(self, workspace: str, services: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = await self._call("POST", "/sessions", {"workspace": workspace, "services": services})
        return result

    async def session(self, sid: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._call("GET", f"/sessions/{sid}")
        return result

    async def add_services(self, sid: str, services: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = await self._call("POST", f"/sessions/{sid}/services", services)
        return result

    async def run_sql(self, sid: str, service: str, sql: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._call("POST", f"/sessions/{sid}/services/{service}/sql", {"sql": sql})
        return result

    async def delete_session(self, sid: str) -> None:
        await self._call("DELETE", f"/sessions/{sid}")

    async def job(self, sid: str, spec: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Events of one command: start, output…, truncated?, exit."""
        try:
            async with self.http.stream("POST", f"/sessions/{sid}/jobs", json=spec) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise SandboxRequestError(response.status_code, _detail(response))
                async for line in response.aiter_lines():
                    if line.strip():
                        yield json.loads(line)
        except httpx.HTTPError as e:
            raise SandboxUnavailable(f"Lost the sandbox runner during a job ({e.__class__.__name__}).") from e

    async def start_preview(self, sid: str, spec: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = await self._call("POST", f"/sessions/{sid}/previews", spec)
        return result

    async def preview(self, sid: str, pid: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._call("GET", f"/sessions/{sid}/previews/{pid}")
        return result

    async def preview_output(self, sid: str, pid: str) -> AsyncIterator[bytes]:
        try:
            async with self.http.stream("GET", f"/sessions/{sid}/previews/{pid}/output") as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise SandboxRequestError(response.status_code, _detail(response))
                async for chunk in response.aiter_raw():
                    yield chunk
        except httpx.HTTPError as e:
            raise SandboxUnavailable(str(e)) from e

    async def send_input(self, sid: str, pid: str, data: str) -> None:
        await self._call("POST", f"/sessions/{sid}/previews/{pid}/input", {"data": data})

    async def resize(self, sid: str, pid: str, rows: int, cols: int) -> None:
        await self._call("POST", f"/sessions/{sid}/previews/{pid}/resize", {"rows": rows, "cols": cols})

    async def stop_preview(self, sid: str, pid: str) -> None:
        await self._call("DELETE", f"/sessions/{sid}/previews/{pid}")


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    return detail if isinstance(detail, str) else json.dumps(detail)[:500]
