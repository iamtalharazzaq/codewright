"""Run the Phase 1 example team against a real model server.

    uv run python -m agent.agents.demo --url http://127.0.0.1:8080/v1 --workspace /tmp/codewright-demo

Prints what the Project Manager answered, which files the Business Analyst wrote, tokens and time.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from langchain_core.callbacks import UsageMetadataCallbackHandler

from agent.agents.team import build_team
from agent.llm.client import LLMClient
from agent.llm.config import LLMProfile
from agent.llm.langchain_model import chat_model


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", default="Qwen3.5-9B-Q4_K_M")
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()

    args.workspace.mkdir(parents=True, exist_ok=True)
    client = LLMClient("local_cpu", LLMProfile(base_url=args.url, model=args.model, num_ctx=4096))
    usage = UsageMetadataCallbackHandler()
    team = build_team(chat_model(client, max_tokens=400), args.workspace)
    start = time.monotonic()
    result = await team.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Start intake for project 'goshop' (Go + React, PostgreSQL). Ask the business "
                    "analyst to write /intake/notes.md with the goals: architecture audit, team autonomy. "
                    "Delivery: local folder.",
                }
            ]
        },
        config={"callbacks": [usage], "recursion_limit": 40},
    )
    elapsed = time.monotonic() - start
    print("PM answer:", result["messages"][-1].content)
    print("Files:", sorted(str(p.relative_to(args.workspace)) for p in args.workspace.rglob("*") if p.is_file()))
    for path in args.workspace.rglob("*.md"):
        print(f"--- {path.relative_to(args.workspace)}\n{path.read_text()}")
    print("Usage:", usage.usage_metadata)
    print(f"Time: {elapsed:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
