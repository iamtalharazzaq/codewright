# 0007. LLM layer: llama.cpp for both profiles, grammar-constrained structured outputs

- **Status:** accepted (amends the "Ollama for remote_gpu" part of ADR 0002)
- **Date:** 2026-10-26
- **Phase:** 1

## Context
The user hosts the model with **llama.cpp** and uses it through its API, both locally (CPU) and on the remote RTX 3080;
switching should only change the URL. The model is a 9B, so structured decisions must be reliable, and context is tight
(the local server runs 4 slots × 4096 tokens).

Verified against the user's llama-server (2026-10-26):
- `response_format: {"type": "json_schema", "json_schema": {"name", "strict", "schema"}}` on `/v1/chat/completions`
  constrains sampling with a grammar; `usage` (prompt/completion tokens) and `timings` are returned.
- `chat_template_kwargs: {"enable_thinking": false}` works **per request** (the README documents it only as a CLI flag).
- `maxLength` in a schema truncates text mid-sentence: put length guidance in the prompt or field description instead.
- `/health` returns 503 while loading, 200 when ready; `/props` gives the per-slot context and slot count.

## Decision
- Both profiles are `server: llamacpp` with an OpenAI-compatible `base_url`. URL precedence: Settings page (DB) >
  `MONOSHIFT_LLM_*_URL` env > `config/models.yaml`. The remote GPU URL is unset until the user provides it.
- `agent/llm/client.py` calls the API directly with httpx (full control of `response_format`, `chat_template_kwargs`,
  usage), one `asyncio.Semaphore(max_parallel_llm_jobs)` per profile+URL, and maps transport errors/503 to
  `LLMUnavailable`. Agent loops (deepagents) use `ChatOpenAI` pointed at the same server with the same sampling and
  `max_retries=0`.
- Structured outputs: Pydantic model → JSON schema (refs inlined, `additionalProperties: false`) → grammar-constrained
  generation → Pydantic validation → up to 2 retries that show the model its answer and the validation error.
- Thinking is off; Qwen non-thinking sampling (temperature 0.7, top_p 0.8, top_k 20).
- Health check reports reachability, per-slot context (warns if smaller than `num_ctx`) and warns if the URL looks
  publicly exposed (public IPs/hostnames; Tailscale `100.64.0.0/10`, private and loopback addresses are fine).
- Embeddings: **Qwen3-Embedding-0.6B** (1024 dimensions), already served on the user's machine (port 8081).

## Consequences
- No Ollama dependency. `ollama-cpu` stays an optional compose profile only.
- Per-role tool allowlists are mandatory (ADR 0009): deepagents' default tools alone cost ~2.6K tokens.
