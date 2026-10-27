"""LangChain chat model for agent loops (deepagents roles). Same server and sampling as `LLMClient`."""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent.llm.client import DEFAULT_SAMPLING, LLMClient, LLMUnavailable


def chat_model(client: LLMClient, *, callbacks: list[BaseCallbackHandler] | None = None, **kwargs: Any) -> ChatOpenAI:
    profile = client.profile
    if not profile.base_url:
        raise LLMUnavailable(f"The {client.name} profile has no URL configured.")
    return ChatOpenAI(
        model=profile.model,
        base_url=profile.base_url,
        # llama-server ignores the key unless started with --api-key; the OpenAI client requires a non-empty value.
        api_key=SecretStr(client.api_key or "not-needed"),
        temperature=DEFAULT_SAMPLING["temperature"],
        top_p=DEFAULT_SAMPLING["top_p"],
        timeout=profile.request_timeout_s,
        max_retries=0,  # retries are the workflow's decision (pause and ask), not the client's
        extra_body={"top_k": DEFAULT_SAMPLING["top_k"], "chat_template_kwargs": {"enable_thinking": False}},
        callbacks=callbacks,
        **kwargs,
    )
