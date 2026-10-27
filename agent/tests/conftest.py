from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel

from agent.llm.client import LLMClient
from agent.llm.config import LLMProfile, ProfileName


class FakeServices:
    """RunServices for tests: records events, hands out preconfigured LLM clients and chat models."""

    def __init__(
        self, clients: dict[str, LLMClient] | None = None, chat_models: dict[str, BaseChatModel] | None = None
    ) -> None:
        self.events: list[tuple[str, str | None, dict[str, Any]]] = []
        self.clients = clients or {}
        self.chat_models = chat_models or {}

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
        self.events.append((event, step, data or {}))

    def llm(self, profile: ProfileName, *, run_id: str, step: str, role: str) -> LLMClient:
        return self.clients.get(profile) or LLMClient(profile, LLMProfile(base_url=None, model="m", num_ctx=4096))

    def chat_model(self, profile: ProfileName, *, run_id: str, step: str, role: str, **kwargs: Any) -> BaseChatModel:
        # Keep the step's callbacks (its usage meter); other kwargs (max_tokens...) are for the real server.
        return self.chat_models[profile].model_copy(update={"callbacks": kwargs.get("callbacks")})


@pytest.fixture
def services() -> FakeServices:
    return FakeServices()


@pytest.fixture
async def pg_url() -> AsyncIterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        if os.environ.get("SKIP_DB_TESTS") == "1":
            pytest.skip("SKIP_DB_TESTS=1")
        pytest.fail("Postgres tests need TEST_DATABASE_URL (or set SKIP_DB_TESTS=1)")
    yield url
