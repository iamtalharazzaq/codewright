"""Role agents (README Section 4): each role has its own prompt, tool allowlist and context.

Prompts live in `agent/agents/<role>/prompt.md` and the allowlist in `config.yaml`. The allowlist is enforced twice:
tools outside it are hidden from the model (smaller prompt for a 9B model) and any call to them is refused.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

AGENTS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class RoleConfig:
    folder: str
    name: str
    description: str
    tools: tuple[str, ...]
    prompt: str


@cache
def load_role(folder: str) -> RoleConfig:
    base = AGENTS_DIR / folder
    config = yaml.safe_load((base / "config.yaml").read_text(encoding="utf-8"))
    return RoleConfig(
        folder=folder,
        name=config["name"],
        description=config["description"],
        tools=tuple(config["tools"]),
        prompt=(base / "prompt.md").read_text(encoding="utf-8").strip(),
    )


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        name = tool.get("name") or tool.get("function", {}).get("name")
        return name if isinstance(name, str) else None
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


class ToolAllowlistMiddleware(AgentMiddleware[Any, Any, Any]):
    """Show the model only the allowed tools, and refuse calls to anything else."""

    def __init__(self, allowed: tuple[str, ...] | list[str]) -> None:
        super().__init__()
        self.allowed = frozenset(allowed)

    @property
    def name(self) -> str:
        return "ToolAllowlistMiddleware"

    def _filter(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        return request.override(tools=[t for t in request.tools if _tool_name(t) in self.allowed])

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> Any:
        return handler(self._filter(request))

    async def awrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]]
    ) -> Any:
        return await handler(self._filter(request))

    def _refusal(self, request: ToolCallRequest) -> ToolMessage | None:
        name = request.tool_call["name"]
        if name in self.allowed:
            return None
        return ToolMessage(
            content=f"Tool {name!r} is not available to this role. Allowed: {', '.join(sorted(self.allowed))}.",
            tool_call_id=request.tool_call["id"],
            status="error",
        )

    def wrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]]
    ) -> ToolMessage | Command[Any]:
        return self._refusal(request) or handler(request)

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]
    ) -> ToolMessage | Command[Any]:
        return self._refusal(request) or await handler(request)
