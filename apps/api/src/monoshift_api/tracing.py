"""Built-in trace store (README 7.2): every LLM call is written to Postgres, tagged with run, step and role."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.llm.client import TraceRecord, TraceSink
from monoshift_api.db import Trace

log = logging.getLogger(__name__)


class PostgresTraceSink:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        run_id: uuid.UUID | None = None,
        step: str | None = None,
        role: str | None = None,
    ) -> None:
        self._sessions = sessions
        self.run_id = run_id
        self.step = step
        self.role = role

    async def record(self, trace: TraceRecord) -> None:
        # Tracing must never break a run: log and carry on if the write fails.
        try:
            async with self._sessions() as session:
                session.add(
                    Trace(
                        run_id=self.run_id,
                        step=self.step,
                        role=self.role,
                        kind=trace.kind,
                        name=trace.name,
                        profile=trace.profile,
                        model=trace.model,
                        input=trace.input,
                        output=trace.output,
                        prompt_tokens=trace.usage.prompt_tokens,
                        completion_tokens=trace.usage.completion_tokens,
                        latency_ms=trace.latency_ms,
                        status=trace.status,
                        error=trace.error,
                        meta=trace.metadata,
                    )
                )
                await session.commit()
        except Exception:
            log.exception("could not store trace %s", trace.name)


class LangfuseTraceSink:
    """Optional: also send each LLM call to a self-hosted Langfuse (README 3: "optional Langfuse profile").

    Enabled when LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL are set. Point it only at your own
    Langfuse: traces contain prompts, i.e. pieces of the analyzed code."""

    def __init__(self, client: Any, *, run_id: uuid.UUID | None, step: str | None, role: str | None) -> None:
        self._client = client
        self._context = {"run_id": str(run_id) if run_id else None, "step": step, "role": role}

    async def record(self, trace: TraceRecord) -> None:
        try:
            generation = self._client.start_observation(
                name=f"{self._context['step'] or 'llm'}.{trace.name}",
                as_type="generation",
                model=trace.model,
                input=trace.input,
                output=trace.output,
                metadata={**self._context, **trace.metadata, "profile": trace.profile, "latency_ms": trace.latency_ms},
                usage_details={
                    "input_tokens": trace.usage.prompt_tokens,
                    "output_tokens": trace.usage.completion_tokens,
                },
                level="ERROR" if trace.status == "error" else "DEFAULT",
                status_message=trace.error,
            )
            generation.end()
        except Exception:
            log.exception("could not send trace %s to Langfuse", trace.name)


class FanOutTraceSink:
    def __init__(self, *sinks: TraceSink) -> None:
        self.sinks = sinks

    async def record(self, trace: TraceRecord) -> None:
        for sink in self.sinks:
            await sink.record(trace)


def langfuse_client() -> Any | None:
    """A Langfuse client if it's configured, else None. Never raises."""
    if not all(os.environ.get(k) for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")):
        return None
    try:
        from langfuse import get_client  # noqa: PLC0415  (optional dependency)
    except ImportError:
        log.warning("LANGFUSE_* is set but the langfuse package is not installed; skipping Langfuse")
        return None
    return get_client()
