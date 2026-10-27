from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest

from agent.llm.client import LLMClient
from agent.llm.config import LLMProfile, ProfileName


class FakeServices:
    """RunServices for tests: records events, hands out preconfigured LLM clients."""

    def __init__(self, clients: dict[str, LLMClient] | None = None) -> None:
        self.events: list[tuple[str, str | None, dict[str, Any]]] = []
        self.clients = clients or {}

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
        self.events.append((event, step, data or {}))

    def llm(self, profile: ProfileName, *, run_id: str, step: str, role: str) -> LLMClient:
        return self.clients.get(profile) or LLMClient(profile, LLMProfile(base_url=None, model="m", num_ctx=4096))


@pytest.fixture
def services() -> FakeServices:
    return FakeServices()


@pytest.fixture
async def pg_url() -> AsyncIterator[str]:
    url = os.environ.get("MONOSHIFT_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("MONOSHIFT_SKIP_DB_TESTS") == "1":
            pytest.skip("MONOSHIFT_SKIP_DB_TESTS=1")
        pytest.fail("Postgres tests need MONOSHIFT_TEST_DATABASE_URL (or set MONOSHIFT_SKIP_DB_TESTS=1)")
    yield url
