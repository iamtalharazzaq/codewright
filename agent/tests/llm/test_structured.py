from __future__ import annotations

import json
from typing import Any, Literal

import httpx
import pytest
from pydantic import BaseModel, Field

from agent.llm.client import LLMClient
from agent.llm.config import LLMProfile
from agent.llm.structured import StructuredOutputError, schema_for, structured


class Reason(BaseModel):
    text: str


class Owner(BaseModel):
    service: Literal["user", "order", "payment"]
    confidence: float = Field(ge=0, le=1)
    reason: Reason


def client_returning(*contents: str) -> tuple[LLMClient, list[dict[str, Any]]]:
    bodies: list[dict[str, Any]] = []
    queue = list(contents)

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": queue.pop(0)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )

    prof = LLMProfile(base_url="http://llm.internal/v1", model="m", num_ctx=4096)
    return LLMClient("local_cpu", prof, transport=httpx.MockTransport(handler)), bodies


def test_schema_inlines_refs_and_forbids_extra_keys() -> None:
    schema = schema_for(Owner)
    assert "$defs" not in schema
    assert schema["additionalProperties"] is False
    assert schema["properties"]["reason"]["additionalProperties"] is False
    assert schema["properties"]["service"]["enum"] == ["user", "order", "payment"]


async def test_valid_first_try() -> None:
    client, _ = client_returning('{"service":"payment","confidence":0.9,"reason":{"text":"owns payments"}}')
    res = await structured(client, Owner, [{"role": "user", "content": "?"}], task="owner")
    assert res.value.service == "payment" and res.first_try and res.usage.total_tokens == 10


async def test_retry_feeds_back_the_validation_error() -> None:
    client, bodies = client_returning(
        '{"service":"payment","confidence":7,"reason":{"text":"x"}}',
        '{"service":"payment","confidence":0.7,"reason":{"text":"x"}}',
    )
    res = await structured(client, Owner, [{"role": "user", "content": "?"}], task="owner")
    assert res.value.confidence == 0.7 and len(res.attempts) == 2 and not res.first_try
    feedback = bodies[1]["messages"][-1]["content"]
    assert "confidence" in feedback and "invalid" in feedback


async def test_gives_up_after_budget() -> None:
    client, _ = client_returning("nope", "still nope")
    with pytest.raises(StructuredOutputError) as info:
        await structured(client, Owner, [], task="owner", max_retries=1)
    assert len(info.value.attempts) == 2


class Titled(BaseModel):
    title: str = Field(description="A field that happens to be called title.")
    sections: list[str]


def test_schema_keeps_fields_named_title() -> None:
    # Pydantic's "title" annotations are dropped, but a *field* called title must survive (it's required).
    schema = schema_for(Titled)
    assert set(schema["properties"]) == {"title", "sections"}
    assert schema["required"] == ["title", "sections"]
    assert "title" not in schema["properties"]["title"]
