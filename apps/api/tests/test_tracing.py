from __future__ import annotations

import uuid
from typing import Any

import pytest

from agent.llm.client import TraceRecord, Usage
from monoshift_api import tracing


class FakeGeneration:
    def __init__(self, kwargs: dict[str, Any]) -> None:
        self.kwargs = kwargs
        self.ended = False

    def end(self) -> None:
        self.ended = True


class FakeLangfuse:
    def __init__(self) -> None:
        self.generations: list[FakeGeneration] = []

    def start_observation(self, **kwargs: Any) -> FakeGeneration:
        gen = FakeGeneration(kwargs)
        self.generations.append(gen)
        return gen


def record(status: str = "ok") -> TraceRecord:
    return TraceRecord(
        kind="llm",
        name="intake_summary",
        profile="local_cpu",
        model="qwen",
        input=[{"role": "user", "content": "hi"}],
        output="{}",
        usage=Usage(10, 5),
        latency_ms=1200,
        status=status,  # type: ignore[arg-type]
        error="boom" if status == "error" else None,
        metadata={"attempt": 1},
    )


async def test_langfuse_sink_sends_a_generation_with_usage() -> None:
    client = FakeLangfuse()
    run_id = uuid.uuid4()
    sink = tracing.LangfuseTraceSink(client, run_id=run_id, step="intake", role="business_analyst")
    await sink.record(record("error"))
    [gen] = client.generations
    assert gen.ended
    assert gen.kwargs["as_type"] == "generation"
    assert gen.kwargs["name"] == "intake.intake_summary"
    assert gen.kwargs["usage_details"] == {"input_tokens": 10, "output_tokens": 5}
    assert gen.kwargs["level"] == "ERROR" and gen.kwargs["status_message"] == "boom"
    assert gen.kwargs["metadata"]["run_id"] == str(run_id)


async def test_langfuse_failures_never_break_a_run() -> None:
    class Broken:
        def start_observation(self, **kwargs: Any) -> Any:
            raise RuntimeError("langfuse down")

    await tracing.LangfuseTraceSink(Broken(), run_id=None, step=None, role=None).record(record())


def test_langfuse_is_off_unless_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    assert tracing.langfuse_client() is None
