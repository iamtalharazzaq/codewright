"""What playbook nodes may use from the outside world. The API's run manager provides the real implementation;
tests provide fakes. Nodes never import the API, the database or HTTP clients directly."""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel

from agent.llm.client import LLMClient
from agent.llm.config import ProfileName


class RunServices(Protocol):
    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
        """Publish a durable run event (timeline, plan updates, artifacts). Stored before the node continues."""

    def llm(self, profile: ProfileName, *, run_id: str, step: str, role: str) -> LLMClient:
        """An LLM client whose calls are traced against this run, step and role."""

    def chat_model(self, profile: ProfileName, *, run_id: str, step: str, role: str, **kwargs: Any) -> BaseChatModel:
        """A LangChain chat model for agent loops (deepagents), on the same server, traced the same way."""
