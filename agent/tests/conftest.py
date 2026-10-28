from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel

from agent.llm.client import LLMClient
from agent.llm.config import LLMProfile, ProfileName


class FakeProject:
    """ProjectTools for tests: a folder, a module graph, canned search hits and linter output."""

    def __init__(
        self,
        work: Path,
        graph: dict[str, Any] | None = None,
        *,
        summary: dict[str, Any] | None = None,
        lint_outputs: list[dict[str, Any]] | None = None,
        hits: list[dict[str, Any]] | None = None,
        test_results: list[list[dict[str, Any]]] | None = None,
        recordings: list[dict[str, Any]] | None = None,
        verifications: dict[str, list[dict[str, Any]]] | None = None,
        audit_outputs: list[dict[str, Any]] | None = None,
        step_results: dict[str, list[dict[str, Any]]] | None = None,
        trial: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> None:
        self._work = work
        self.graph = graph
        self._summary = summary or {}
        self.lint_outputs = lint_outputs or []
        self.hits = hits or []
        # `test()`'s answer, one call at a time (so a test can see "before" fails, "after" passes); the last one
        # given repeats once the list runs out.
        self._test_results = test_results or [[{"component": ".", "pack": "", "ok": True, "report": None}]]
        self.saved_facts: list[dict[str, Any]] = []
        self.linted: list[list[str] | None] = []
        self.actions: list[str] = []
        self.tested: list[list[str] | None] = []
        self._recordings = recordings or []
        self._audit_outputs = audit_outputs
        self._step_results = step_results or {}
        self._trial = trial
        self.steps_run: list[tuple[str, list[str]]] = []
        self.trials: list[tuple[str, list[str]]] = []
        # `verify(action)`'s answers, one call at a time per action; an action with none says it could not run.
        self._verifications = verifications or {}
        self.verified: list[str] = []
        self.changed: list[str] = []

    @property
    def work(self) -> Path:
        return self._work

    async def summary(self) -> dict[str, Any]:
        return self._summary

    async def fresh_graph(self) -> dict[str, Any] | None:
        return self.graph

    def graph_versions(self) -> list[dict[str, Any]]:
        return [{"number": 1, "hygiene": {"isolated_modules": [], "mutual_dependencies": []}}] if self.graph else []

    def explain(self, name: str) -> str:
        return f"Node: {name}"

    async def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        return self.hits[:limit]

    async def lint(self, paths: list[str] | None = None) -> list[dict[str, Any]]:
        self.linted.append(paths)
        return self.lint_outputs

    async def sandbox(self, action: str, paths: list[str] | None = None) -> list[dict[str, Any]]:
        self.actions.append(action)
        if action == "lint":
            return self.lint_outputs
        if action == "audit" and self._audit_outputs is not None:
            return self._audit_outputs
        return [{"component": ".", "step": action, "ok": True, "output": ""}]

    async def test(self, paths: list[str] | None = None) -> list[dict[str, Any]]:
        self.tested.append(paths)
        i = min(len(self.tested) - 1, len(self._test_results) - 1)
        return self._test_results[i]

    async def run_step(self, step: Any) -> dict[str, Any]:
        self.steps_run.append((step.name, list(step.cmd)))
        answers = self._step_results.get(step.name)
        if not answers:
            return {"ok": True, "exit_code": 0, "output": ""}
        return answers.pop(0) if len(answers) > 1 else answers[0]

    async def db_trial(self, up_file: str, queries: list[str]) -> dict[str, Any]:
        self.trials.append((up_file, queries))
        if isinstance(self._trial, list):
            return self._trial.pop(0) if len(self._trial) > 1 else self._trial[0]
        return self._trial or {"ok": None, "error": "not available in this test"}

    def recordings(self) -> list[dict[str, Any]]:
        return self._recordings

    async def verify(self, action: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        self.verified.append(action)
        answers = self._verifications.get(action)
        if not answers:
            return {"ok": None, "error": "not available in this test", "report": None}
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def files_changed(self, paths: list[str]) -> None:
        self.changed.extend(paths)

    def facts(self) -> list[dict[str, Any]]:
        return self.saved_facts

    async def add_facts(self, facts: list[dict[str, Any]]) -> None:
        self.saved_facts.extend(facts)


class FakeServices:
    """RunServices for tests: records events, hands out preconfigured LLM clients and chat models."""

    def __init__(
        self,
        clients: dict[str, LLMClient] | None = None,
        chat_models: dict[str, BaseChatModel] | None = None,
        project: FakeProject | None = None,
    ) -> None:
        self.events: list[tuple[str, str | None, dict[str, Any]]] = []
        self.clients = clients or {}
        self.chat_models = chat_models or {}
        self._project = project

    async def emit(
        self, run_id: str, event: str, *, step: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
        self.events.append((event, step, data or {}))

    def llm(self, profile: ProfileName, *, run_id: str, step: str, role: str) -> LLMClient:
        return self.clients.get(profile) or LLMClient(profile, LLMProfile(base_url=None, model="m", num_ctx=4096))

    def chat_model(self, profile: ProfileName, *, run_id: str, step: str, role: str, **kwargs: Any) -> BaseChatModel:
        # Keep the step's callbacks (its usage meter); other kwargs (max_tokens...) are for the real server.
        return self.chat_models[profile].model_copy(update={"callbacks": kwargs.get("callbacks")})

    def project(self, project_id: str) -> FakeProject:
        if self._project is None:
            raise RuntimeError("no project in this test")
        return self._project


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
