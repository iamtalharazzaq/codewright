# 0002. LLM: Qwen3.5 9B Q4_K_M (verification V1)

- **Status:** accepted (VRAM numbers on the RTX 3080 to be measured in Phase 1)
- **Date:** 2026-10-26
- **Phase:** 0

## Context
README C6/V1: the model must exist as a Q4_K_M build for Ollama/llama.cpp and fit a 10 GB GPU at the planned context.

Verified facts (2026-10-26):
- **Ollama:** `qwen3.5:9b-q4_K_M` exists (6.6 GB, includes the vision projector), 256K max context
  (https://ollama.com/library/qwen3.5/tags). The default `qwen3.5:9b` tag is also Q4_K_M.
- **GGUF / llama.cpp:** `Qwen3.5-9B-Q4_K_M.gguf` is 5,680,522,464 bytes (5.29 GiB). It already runs on this machine
  (llama.cpp snap build, `--no-mmproj`).
- **Architecture** (https://huggingface.co/Qwen/Qwen3.5-9B): 32 layers in the pattern 8 × (3 × Gated DeltaNet + 1 ×
  Gated Attention). Only the **8 full-attention layers** keep a KV cache: 4 KV heads × head dim 256. Apache-2.0. A
  vision-language model; thinking is **on by default** and is disabled with `chat_template_kwargs: {enable_thinking: false}`.

VRAM estimate (f16 KV cache):

| Context | KV cache (8 layers × 2 × 4 × 256 × 2 B = 32 KiB/token) | Weights | DeltaNet state + compute (rough) | Total |
|---|---|---|---|---|
| 8K | 0.25 GiB | 5.29 GiB | ~0.6–1.0 GiB | ~6.2–6.5 GiB |
| 16K | 0.5 GiB | 5.29 GiB | ~0.6–1.0 GiB | ~6.4–6.8 GiB |
| 32K | 1.0 GiB | 5.29 GiB | ~0.6–1.0 GiB | ~6.9–7.3 GiB |

So 16K (and very likely 32K) fits 10 GB with room to spare; text-only (`--no-mmproj`) saves the projector's memory.
These are estimates; the README requires measuring on the real RTX 3080 (Phase 1, `docs/setup/remote-gpu.md`).

Measured on this machine's CPU (llama.cpp, 4 slots × 4K, other load present): ~10 tokens/s prompt processing,
~4.9 tokens/s generation. A small JSON-mode request returned valid JSON in 13 s.

## Decision
- Keep **Qwen3.5 9B Q4_K_M**; no fallback model needed.
- `config/models.yaml` uses the Ollama tag `qwen3.5:9b-q4_K_M` for `remote_gpu` and the GGUF via llama.cpp for
  `local_cpu`. Both are reached through their OpenAI-compatible `/v1` API.
- All structured tasks run with **thinking disabled** and the Qwen non-thinking sampling settings, unless an eval shows
  thinking helps a specific task type (Phase 1 / Phase 15).
- Run text-only (`--no-mmproj` on llama.cpp). Vision may be useful later (UI screenshots, Phase 12); revisit then.
- Start with `num_ctx` 16384 on the GPU and 8192 on CPU; measure and tune in Phase 1.

## Consequences
- The CPU profile is slow (~5 tok/s): fine for audits, too slow for full conversions, as the README expects.
- The API container reaches a host model server via `host.docker.internal`. A server bound to `127.0.0.1` on the host
  (like the current llama-server) is **not** reachable from containers: either bind it to the Docker bridge, use the
  bundled `llamacpp-cpu` compose profile (mounts `MONOSHIFT_MODELS_DIR` read-only, no copy), or run the API on the host.
  To be settled in Phase 1.
