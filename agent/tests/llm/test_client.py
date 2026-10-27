from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from agent.llm.client import LLMClient, LLMError, LLMUnavailable, TraceRecord, exposure_warnings
from agent.llm.config import LLMProfile


class RecordingSink:
    def __init__(self) -> None:
        self.records: list[TraceRecord] = []

    async def record(self, trace: TraceRecord) -> None:
        self.records.append(trace)


def profile(**kw: Any) -> LLMProfile:
    data: dict[str, Any] = {"base_url": "http://llm.internal:8080/v1", "model": "qwen", "num_ctx": 4096}
    data.update(kw)
    return LLMProfile(**data)


def completion(content: str, finish: str = "stop") -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


async def test_chat_sends_schema_and_disables_thinking_and_traces() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        seen["url"] = str(req.url)
        return httpx.Response(200, json=completion('{"a": 1}'))

    sink = RecordingSink()
    client = LLMClient("local_cpu", profile(), tracer=sink, transport=httpx.MockTransport(handler))
    result = await client.chat([{"role": "user", "content": "hi"}], name="t", json_schema={"type": "object"})

    assert result.content == '{"a": 1}'
    assert result.usage.total_tokens == 18
    assert seen["url"] == "http://llm.internal:8080/v1/chat/completions"
    assert seen["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["response_format"]["type"] == "json_schema"
    assert seen["response_format"]["json_schema"]["schema"] == {"type": "object"}
    [trace] = sink.records
    assert trace.status == "ok" and trace.usage.completion_tokens == 7 and trace.profile == "local_cpu"


async def test_connection_error_is_unavailable_and_traced() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    sink = RecordingSink()
    client = LLMClient("remote_gpu", profile(), tracer=sink, transport=httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailable):
        await client.chat([{"role": "user", "content": "x"}], name="t")
    assert sink.records[0].status == "error"


async def test_503_is_unavailable_and_500_is_error() -> None:
    codes = iter([503, 500])
    client = LLMClient(
        "local_cpu", profile(), transport=httpx.MockTransport(lambda r: httpx.Response(next(codes), text="x"))
    )
    with pytest.raises(LLMUnavailable):
        await client.chat([], name="t")
    with pytest.raises(LLMError) as info:
        await client.chat([], name="t")
    assert not isinstance(info.value, LLMUnavailable)


async def test_unconfigured_profile() -> None:
    client = LLMClient("remote_gpu", profile(base_url=None))
    assert (await client.health()).status == "not_configured"
    with pytest.raises(LLMUnavailable):
        await client.chat([], name="t")


async def test_health_reads_props_and_warns_on_small_context() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(
            200, json={"default_generation_settings": {"n_ctx": 2048}, "total_slots": 4, "model_path": "m.gguf"}
        )

    client = LLMClient("local_cpu", profile(num_ctx=4096), transport=httpx.MockTransport(handler))
    report = await client.health()
    assert report.ok and report.server_ctx == 2048 and report.server_slots == 4
    assert any("per-slot context is 2048" in w for w in report.warnings)


async def test_health_loading_and_unreachable() -> None:
    loading = LLMClient("local_cpu", profile(), transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert (await loading.health()).status == "loading"

    def refuse(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    down = LLMClient("local_cpu", profile(), transport=httpx.MockTransport(refuse))
    assert (await down.health()).status == "unreachable"


async def test_queue_limits_parallel_requests() -> None:
    active = 0
    peak = 0

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return httpx.Response(200, json=completion("ok"))

    client = LLMClient("local_cpu", profile(base_url="http://queue-test:1/v1"), transport=httpx.MockTransport(handler))
    await asyncio.gather(*(client.chat([], name="t") for _ in range(4)))
    assert peak == 1


@pytest.mark.parametrize(
    ("url", "warns"),
    [
        ("http://127.0.0.1:8080/v1", False),
        ("http://host.docker.internal:8080/v1", False),
        ("http://100.101.102.103:8080/v1", False),  # Tailscale
        ("http://gpu-box.tailnet:8080/v1", False),
        ("http://8.8.8.8:8080/v1", True),
        ("http://llm.example.com/v1", True),
    ],
)
def test_exposure_warnings(url: str, warns: bool) -> None:
    assert bool(exposure_warnings(url)) is warns
