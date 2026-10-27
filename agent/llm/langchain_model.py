"""LangChain chat model for agent loops (deepagents roles). Same server, sampling, queue and tracing as `LLMClient`."""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from typing import Any

import httpx
import openai
from langchain_core.callbacks import AsyncCallbackHandler, BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent.llm.client import (
    DEFAULT_SAMPLING,
    MAX_TRACE_CHARS,
    LLMClient,
    LLMUnavailable,
    QueuedTransport,
    TraceRecord,
    Usage,
)

# What the OpenAI SDK raises when the model server is gone or overloaded. Agent steps turn these into
# `LLMUnavailable`, so the run pauses and asks (README Section 10) instead of failing.
UNAVAILABLE_ERRORS: tuple[type[Exception], ...] = (
    openai.APIConnectionError,  # includes APITimeoutError
    openai.InternalServerError,  # 5xx, e.g. 503 while the model loads
)


class TraceCallback(AsyncCallbackHandler):
    """Writes every chat-model call to the client's trace sink, like `LLMClient.chat` does."""

    def __init__(self, client: LLMClient, name: str) -> None:
        self.client = client
        self.name = name
        self._started: dict[uuid.UUID, tuple[float, list[dict[str, str]]]] = {}

    async def on_chat_model_start(
        self, serialized: dict[str, Any], messages: list[list[BaseMessage]], *, run_id: uuid.UUID, **kwargs: Any
    ) -> None:
        flat = [{"role": m.type, "content": str(m.content)[:MAX_TRACE_CHARS]} for m in messages[0]]
        self._started[run_id] = (time.monotonic(), flat)

    async def on_llm_end(self, response: LLMResult, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        start, messages = self._started.pop(run_id, (time.monotonic(), []))
        generation = response.generations[0][0] if response.generations and response.generations[0] else None
        output = generation.text if generation else ""
        usage = Usage()
        tool_calls: list[str] = []
        if isinstance(generation, ChatGeneration):
            meta = getattr(generation.message, "usage_metadata", None) or {}
            usage = Usage(int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0)))
            tool_calls = [c["name"] for c in getattr(generation.message, "tool_calls", [])]
        await self._record(start, messages, output, usage, None, {"tool_calls": tool_calls} if tool_calls else {})

    async def on_llm_error(self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        start, messages = self._started.pop(run_id, (time.monotonic(), []))
        await self._record(start, messages, None, Usage(), f"{type(error).__name__}: {error}", {})

    async def _record(
        self,
        start: float,
        messages: Sequence[dict[str, str]],
        output: str | None,
        usage: Usage,
        error: str | None,
        metadata: dict[str, Any],
    ) -> None:
        await self.client.tracer.record(
            TraceRecord(
                kind="llm",
                name=self.name,
                profile=self.client.name,
                model=self.client.profile.model,
                input=list(messages),
                output=output[:MAX_TRACE_CHARS] if output is not None else None,
                usage=usage,
                latency_ms=int((time.monotonic() - start) * 1000),
                status="error" if error else "ok",
                error=error,
                metadata={"agent_loop": True, **metadata},
            )
        )


class UsageMeter(AsyncCallbackHandler):
    """Counts chat-model calls and tokens for one task (budget accounting)."""

    def __init__(self) -> None:
        self.llm_calls = 0
        self.tokens = 0

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        self.llm_calls += 1
        for generations in response.generations:
            for generation in generations:
                if isinstance(generation, ChatGeneration):
                    meta = getattr(generation.message, "usage_metadata", None) or {}
                    self.tokens += int(meta.get("total_tokens", 0))


def chat_model(
    client: LLMClient,
    *,
    callbacks: list[BaseCallbackHandler] | None = None,
    trace_name: str = "agent",
    **kwargs: Any,
) -> ChatOpenAI:
    profile = client.profile
    if not profile.base_url:
        raise LLMUnavailable(f"The {client.name} profile has no URL configured.")
    return ChatOpenAI(
        model=profile.model,
        base_url=profile.base_url,
        # llama-server ignores the key unless started with --api-key; the OpenAI client requires a non-empty value.
        api_key=SecretStr(client.api_key or "not-needed"),
        temperature=DEFAULT_SAMPLING["temperature"],
        top_p=DEFAULT_SAMPLING["top_p"],
        timeout=profile.http_timeout(),
        max_retries=0,  # retries are the workflow's decision (pause and ask), not the client's
        stream_usage=True,  # token counts also when LangGraph streams the reply (budgets, traces)
        http_async_client=httpx.AsyncClient(
            transport=QueuedTransport(client.name, profile), timeout=profile.http_timeout()
        ),
        extra_body={"top_k": DEFAULT_SAMPLING["top_k"], "chat_template_kwargs": {"enable_thinking": False}},
        callbacks=[TraceCallback(client, trace_name), *(callbacks or [])],
        **kwargs,
    )
