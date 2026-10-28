"""What playbook nodes may use from the outside world. The API's run manager provides the real implementation;
tests provide fakes. Nodes never import the API, the database or HTTP clients directly."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel

from agent.llm.client import LLMClient
from agent.llm.config import ProfileName


class ProjectTools(Protocol):
    """A project as playbook nodes may use it (read-only, except the facts the user confirmed)."""

    @property
    def work(self) -> Path:
        """The project's working copy (`workspaces/<id>/work`)."""

    async def summary(self) -> dict[str, Any]:
        """The project's name, and the files, languages, top level and secrets found at import (Project.summary)."""

    async def fresh_graph(self) -> dict[str, Any] | None:
        """The module graph after any pending update (built now if the project has none yet), with user facts."""

    def graph_versions(self) -> list[dict[str, Any]]:
        """Graph versions with their hygiene reports, oldest first."""

    def explain(self, name: str) -> str:
        """Graphify's `explain` for a symbol or node id."""

    async def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """Code search hits: path, start_line, end_line, content."""

    async def lint(self, paths: list[str] | None = None) -> list[dict[str, Any]]:
        """Run each component's linters in the sandbox: [{component, pack, step, ok, output}] per step."""

    async def sandbox(self, action: str, paths: list[str] | None = None) -> list[dict[str, Any]]:
        """Run `build`, `test` or `lint` for the components in the sandbox; output per step as for `lint`."""

    def files_changed(self, paths: list[str]) -> None:
        """Files were written in `work/`: update the graph and search (throttled)."""

    def facts(self) -> list[dict[str, Any]]:
        """Corrections the user confirmed (USER_FACT)."""

    async def add_facts(self, facts: list[dict[str, Any]]) -> None:
        """Save confirmed facts on the graph (and in the project memory)."""


class RunServices(Protocol):
    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
        """Publish a durable run event (timeline, plan updates, artifacts). Stored before the node continues."""

    def llm(self, profile: ProfileName, *, run_id: str, step: str, role: str) -> LLMClient:
        """An LLM client whose calls are traced against this run, step and role."""

    def chat_model(self, profile: ProfileName, *, run_id: str, step: str, role: str, **kwargs: Any) -> BaseChatModel:
        """A LangChain chat model for agent loops (deepagents), on the same server, traced the same way."""

    def project(self, project_id: str) -> ProjectTools:
        """The run's project (graph, search, sandbox linters, facts). Only for playbooks with `needs_project`."""
