"""Structured outputs for a small model (README Section 8.2, rule 3).

Every decision is a Pydantic model. Its JSON schema is sent to llama.cpp, which constrains sampling with a grammar so
the output is syntactically valid JSON of the right shape. The result is then validated by Pydantic (which also checks
what grammars can't, e.g. cross-field rules). On failure the model sees its own answer plus the validation error and
gets a bounded number of retries.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from agent.llm.client import LLMClient, LLMError, Message, Usage

DEFAULT_MAX_RETRIES = 2


class StructuredOutputError(LLMError):
    """The model didn't produce a valid answer within the retry budget."""

    def __init__(self, message: str, attempts: list[Attempt]) -> None:
        super().__init__(message)
        self.attempts = attempts


@dataclass(frozen=True)
class Attempt:
    raw: str
    error: str | None


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    value: T
    attempts: list[Attempt] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0

    @property
    def first_try(self) -> bool:
        return len(self.attempts) == 1


def schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema for llama.cpp's grammar: inline every $ref and forbid extra keys."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any, *, properties: bool = False) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            if properties:  # keys are field names (a field may be called "title"), values are schemas
                return {k: resolve(v) for k, v in node.items()}
            out = {k: resolve(v, properties=k == "properties") for k, v in node.items() if k != "title"}
            if out.get("type") == "object" and "properties" in out:
                out.setdefault("additionalProperties", False)
            return out
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    resolved: dict[str, Any] = resolve(schema)
    return resolved


async def structured[T: BaseModel](
    client: LLMClient,
    output: type[T],
    messages: Sequence[Message],
    *,
    task: str,
    max_tokens: int = 512,
    max_retries: int = DEFAULT_MAX_RETRIES,
    metadata: dict[str, Any] | None = None,
) -> StructuredResult[T]:
    """Ask for one structured decision. `task` names the task type (used for traces and success-rate evals)."""
    schema = schema_for(output)
    conversation: list[Message] = list(messages)
    attempts: list[Attempt] = []
    usage = Usage()
    latency = 0

    for attempt_no in range(max_retries + 1):
        result = await client.chat(
            conversation,
            name=task,
            max_tokens=max_tokens,
            json_schema=schema,
            metadata={**(metadata or {}), "task": task, "attempt": attempt_no + 1},
        )
        usage += result.usage
        latency += result.latency_ms
        try:
            value = output.model_validate_json(result.content)
        except ValidationError as exc:
            error = _short_errors(exc)
            if result.finish_reason == "length":
                error = f"The answer was cut off at max_tokens. Be shorter. {error}"
            attempts.append(Attempt(result.content, error))
            conversation = [
                *conversation,
                {"role": "assistant", "content": result.content},
                {
                    "role": "user",
                    "content": f"That answer is invalid: {error}\nReply again with only the corrected JSON object.",
                },
            ]
            continue
        attempts.append(Attempt(result.content, None))
        return StructuredResult(value, attempts, usage, latency)

    raise StructuredOutputError(
        f"No valid {output.__name__} after {len(attempts)} attempts for task {task!r}", attempts
    )


def _short_errors(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)
