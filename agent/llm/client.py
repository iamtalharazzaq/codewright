"""Client for the self-hosted model server (llama.cpp's OpenAI-compatible API).

Responsibilities (README Section 8 and Phase 1):
- one request queue per profile, limited to `max_parallel_llm_jobs`
- health check (reachability, model loaded, real server context size, exposure warnings)
- token and time tracking on every call, reported to a `TraceSink`
- a clear `LLMUnavailable` error when the server can't be reached, so the workflow can pause and ask the user
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

import httpx

from agent.llm.config import LLMProfile, ProfileName

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": "..."}

# Qwen3.5 non-thinking sampling (model card). Thinking stays off for structured, scoped tasks (ADR 0002).
DEFAULT_SAMPLING: dict[str, float | int] = {"temperature": 0.7, "top_p": 0.8, "top_k": 20}
MAX_TRACE_CHARS = 20_000


class LLMError(Exception):
    """The server answered, but not with a usable completion."""


class LLMUnavailable(LLMError):
    """The server can't be reached, is still loading, or timed out. The run should pause and ask the user."""


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(self.prompt_tokens + other.prompt_tokens, self.completion_tokens + other.completion_tokens)


@dataclass(frozen=True)
class ChatResult:
    content: str
    usage: Usage
    latency_ms: int
    finish_reason: str | None


@dataclass
class TraceRecord:
    """One LLM call, as stored in the trace store (and optionally sent to Langfuse)."""

    kind: Literal["llm"]
    name: str
    profile: str
    model: str
    input: Any
    output: str | None
    usage: Usage
    latency_ms: int
    status: Literal["ok", "error"]
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class TraceSink(Protocol):
    async def record(self, trace: TraceRecord) -> None: ...


class NullTraceSink:
    async def record(self, trace: TraceRecord) -> None:
        return None


@dataclass(frozen=True)
class HealthReport:
    profile: ProfileName
    status: Literal["ok", "loading", "unreachable", "not_configured", "error"]
    base_url: str | None
    latency_ms: int | None = None
    server_model: str | None = None
    server_ctx: int | None = None
    server_slots: int | None = None
    warnings: tuple[str, ...] = ()
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


# One semaphore per (profile, url): requests to the same server queue up (README 8.1, "Requests queue").
_queues: dict[tuple[str, str], asyncio.Semaphore] = {}


def _queue_for(name: str, profile: LLMProfile) -> asyncio.Semaphore:
    key = (name, profile.base_url or "")
    sem = _queues.get(key)
    if sem is None:
        sem = _queues[key] = asyncio.Semaphore(profile.max_parallel_llm_jobs)
    return sem


class _ReleasingStream(httpx.AsyncByteStream):
    """A response body that frees its queue slot once it has been read or closed (streamed responses included)."""

    def __init__(self, inner: httpx.AsyncByteStream, release: Callable[[], None]) -> None:
        self._inner = inner
        self._release = release

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._inner:
            yield chunk

    async def aclose(self) -> None:
        try:
            await self._inner.aclose()
        finally:
            self._release()


class QueuedTransport(httpx.AsyncBaseTransport):
    """Makes requests from LangChain models (agent loops) wait in the same per-profile queue as `LLMClient.chat`."""

    def __init__(self, name: str, profile: LLMProfile, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self._sem = _queue_for(name, profile)
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await self._sem.acquire()
        released = False

        def release() -> None:
            nonlocal released
            if not released:
                released = True
                self._sem.release()

        try:
            response = await self._inner.handle_async_request(request)
        except BaseException:
            release()
            raise
        assert isinstance(response.stream, httpx.AsyncByteStream)  # noqa: S101  (async transports return async streams)
        response.stream = _ReleasingStream(response.stream, release)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


def _server_root(base_url: str) -> str:
    """`http://host:8080/v1` -> `http://host:8080` (llama.cpp serves /health and /props at the root)."""
    root = base_url.rstrip("/")
    return root.removesuffix("/v1")


def is_public(base_url: str) -> bool:
    """True when the endpoint is reachable from the internet (a public host name or IP, e.g. an ngrok URL)."""
    host = urlparse(base_url).hostname or ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        internal_suffixes = (".internal", ".local", ".lan", ".ts.net", ".tailnet", "localhost")
        return "." in host and not host.endswith(internal_suffixes)
    return ip.is_global and ip not in ipaddress.ip_network("100.64.0.0/10")  # 100.64/10: Tailscale addresses


def exposure_warnings(base_url: str, *, has_api_key: bool = False) -> list[str]:
    """CODEWRIGHT.md Section 11: warn if the model endpoint looks publicly exposed instead of going through a tunnel."""
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    warnings: list[str] = []
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if is_public(base_url) and not has_api_key:
            warnings.append(
                f"{host} is a public URL (e.g. an ngrok tunnel) and no API key is set: anyone who has the URL can use "
                "the model server. Start llama-server with --api-key-file and set REMOTE_GPU_API_KEY, or use Tailscale."
            )
        return warnings
    cgnat = ipaddress.ip_network("100.64.0.0/10")  # Tailscale addresses
    if ip.is_global and ip not in cgnat:
        warnings.append(f"{host} is a public IP address. Use a secure tunnel instead of exposing the model port.")
        if parsed.scheme == "http":
            warnings.append("Traffic to this endpoint is unencrypted (http).")
    return warnings


class LLMClient:
    def __init__(
        self,
        name: ProfileName,
        profile: LLMProfile,
        *,
        tracer: TraceSink | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self.profile = profile
        self.tracer: TraceSink = tracer or NullTraceSink()
        self._transport = transport

    @property
    def api_key(self) -> str | None:
        env = self.profile.api_key_env
        return os.environ.get(env) or None if env else None

    def _http(self, timeout: float | httpx.Timeout) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return httpx.AsyncClient(timeout=timeout, headers=headers, transport=self._transport)

    async def health(self) -> HealthReport:
        base_url = self.profile.base_url
        if not base_url:
            return HealthReport(self.name, "not_configured", None, detail="No URL set for this profile.")
        warnings = exposure_warnings(base_url, has_api_key=bool(self.api_key))
        root = _server_root(base_url)
        start = time.monotonic()
        try:
            async with self._http(timeout=5) as http:
                res = await http.get(f"{root}/health")
                latency = int((time.monotonic() - start) * 1000)
                if res.status_code == 503:
                    return HealthReport(self.name, "loading", base_url, latency, detail="Model is loading.")
                if res.status_code != 200:
                    return HealthReport(
                        self.name, "error", base_url, latency, detail=f"/health returned {res.status_code}"
                    )
                # /health is public; a protected endpoint shows whether the key is accepted and required.
                models = await http.get(f"{root}/v1/models")
                if models.status_code == 401:
                    detail = "The server rejected the API key." if self.api_key else "The server needs an API key."
                    env = self.profile.api_key_env or "the profile's API key variable"
                    return HealthReport(self.name, "error", base_url, latency, detail=f"{detail} Set {env}.")
                if self.api_key and is_public(base_url) and await self._answers_without_key(root):
                    warnings.append(
                        "The server answers without an API key, so the key protects nothing. Restart llama-server "
                        "with --api-key-file (or --api-key)."
                    )
                props = await self._props(http, root)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            return HealthReport(self.name, "unreachable", base_url, detail=f"{type(exc).__name__}: {exc}")

        ctx = props.get("n_ctx")
        if isinstance(ctx, int) and ctx < self.profile.num_ctx:
            warnings.append(
                f"The server's per-slot context is {ctx} tokens, smaller than the configured num_ctx "
                f"{self.profile.num_ctx}. Lower num_ctx or restart llama-server with a larger -c / fewer -np."
            )
        return HealthReport(
            self.name,
            "ok",
            base_url,
            latency,
            server_model=props.get("model"),
            server_ctx=ctx if isinstance(ctx, int) else None,
            server_slots=props.get("slots"),
            warnings=tuple(warnings),
        )

    async def _answers_without_key(self, root: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5, transport=self._transport) as anonymous:
                return (await anonymous.get(f"{root}/v1/models")).status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    async def _props(http: httpx.AsyncClient, root: str) -> dict[str, Any]:
        """llama.cpp `/props` (best effort: other OpenAI-compatible servers may not have it)."""
        try:
            res = await http.get(f"{root}/props")
            if res.status_code != 200:
                return {}
            data = res.json()
        except (httpx.HTTPError, ValueError):
            return {}
        settings = data.get("default_generation_settings") or {}
        return {"n_ctx": settings.get("n_ctx"), "slots": data.get("total_slots"), "model": data.get("model_path")}

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        name: str,
        max_tokens: int = 512,
        json_schema: dict[str, Any] | None = None,
        thinking: bool = False,
        sampling: dict[str, float | int] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatResult:
        """One chat completion. `json_schema` constrains the output with llama.cpp's grammar sampling."""
        if not self.profile.base_url:
            raise LLMUnavailable(f"The {self.name} profile has no URL configured.")
        body: dict[str, Any] = {
            "model": self.profile.model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            **DEFAULT_SAMPLING,
            **(sampling or {}),
            # Per-request switch for Qwen3.5's thinking mode (verified against llama-server, ADR 0002).
            "chat_template_kwargs": {"enable_thinking": thinking},
        }
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": json_schema},
            }

        url = f"{self.profile.base_url.rstrip('/')}/chat/completions"
        start = time.monotonic()
        content: str | None = None
        usage = Usage()
        error: str | None = None
        try:
            async with _queue_for(self.name, self.profile), self._http(self.profile.http_timeout()) as http:
                start = time.monotonic()  # time spent waiting in the queue is not model latency
                res = await http.post(url, json=body)
            if res.status_code == 503:
                raise LLMUnavailable("The model server is loading or overloaded (503).")
            if res.status_code >= 400:
                raise LLMError(f"The model server returned {res.status_code}: {res.text[:300]}")
            data = res.json()
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
            raw_usage = data.get("usage") or {}
            usage = Usage(int(raw_usage.get("prompt_tokens", 0)), int(raw_usage.get("completion_tokens", 0)))
            return ChatResult(content, usage, int((time.monotonic() - start) * 1000), choice.get("finish_reason"))
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise LLMUnavailable(f"Can't reach the {self.name} model server: {error}") from exc
        except LLMError as exc:
            error = str(exc)
            raise
        except (KeyError, IndexError, ValueError) as exc:
            error = f"Malformed response: {exc}"
            raise LLMError(error) from exc
        finally:
            await self.tracer.record(
                TraceRecord(
                    kind="llm",
                    name=name,
                    profile=self.name,
                    model=self.profile.model,
                    input=_truncate(messages),
                    output=content[:MAX_TRACE_CHARS] if content is not None else None,
                    usage=usage,
                    latency_ms=int((time.monotonic() - start) * 1000),
                    status="error" if error else "ok",
                    error=error,
                    metadata=metadata or {},
                )
            )


def _truncate(messages: Sequence[Message]) -> list[Message]:
    return [{**m, "content": m.get("content", "")[:MAX_TRACE_CHARS]} for m in messages]
