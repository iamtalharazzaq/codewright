"""Write code (`write_code`, CODEWRIGHT.md Section 5.1b), chat version: after Start, the code, its tests and a short
explanation are written into the chat, streamed.

Phase 8 adds the full playbook: tests run in the sandbox (Phase 5) and fixed until they pass. Until then the tests are
written but not run, and the Done card says so.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage

from agent.llm.client import LLMClient
from agent.llm.langchain_model import chat_model

SYSTEM = """You are the Backend Developer of Codewright, an AI software team. The user confirmed a plan; write it now.

Reply in Markdown with exactly these sections:
## Code
One fenced code block with the complete, working code in the confirmed language. Idiomatic, clear names, short
comments only where they help.
## Tests
One fenced code block with tests in the language's usual framework (pytest, GoogleTest or plain asserts in main for
C++, Go's testing package, Vitest/Jest for TypeScript/JavaScript). Cover the normal case and the edge cases listed.
## How it works
2-4 sentences, then the time and space complexity.
## How to run
The exact commands to compile/run the code and the tests.

Use only the confirmed language. Don't ask questions; use the plan's choices and sensible defaults."""


def build_prompt(request: str, card: dict[str, Any], answers: Sequence[Sequence[str]]) -> str:
    lines = [f"Request: {request}", f"What: {card.get('what', '')}", f"Language/stack: {card.get('stack', '')}"]
    lines += [f"- {f}" for f in card.get("features", [])]
    for asked, reply in answers:
        lines.append(f"{asked} → {reply}")
    return "\n".join(lines)


async def stream_code(
    client: LLMClient, request: str, card: dict[str, Any], answers: Sequence[Sequence[str]] = ()
) -> AsyncIterator[str]:
    model = chat_model(client, trace_name="write_code", max_tokens=2500)
    messages = [SystemMessage(SYSTEM), HumanMessage(build_prompt(request, card, answers))]
    async for chunk in model.astream(messages):
        if isinstance(chunk, AIMessageChunk) and isinstance(chunk.content, str) and chunk.content:
            yield chunk.content
