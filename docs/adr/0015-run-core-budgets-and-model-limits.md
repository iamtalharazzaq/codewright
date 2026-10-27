# 0015. Generic run core, budgets, streaming and limits for a 9B model (Phase 1)

- **Status:** accepted (VRAM table pending: the user runs `scripts/measure_vram.py` on the GPU machine)
- **Date:** 2026-10-27
- **Phase:** 1

## Context
Phase 1 (CODEWRIGHT.md Section 15) asks for the run pattern every playbook uses: profiles, health, queue, structured
outputs, token/time tracking, budgets, a run subgraph with a Postgres checkpointer, `interrupt()` approvals, event
streaming, a deepagents team on workspace files, traces and GPU-loss handling. The earlier run manager (ADR 0008) drove
one hard-coded workflow (microservices) with `mode` and `options` columns.

Everything below was verified live against the user's GPU: Qwen3.5-9B-Q4_K_M on a native Windows `llama-server`
(`n_ctx` 4096, 1 slot), reached through ngrok. Versions as locked in ADR 0014.

## Decision

**Generic run core (`agent/playbooks/`).**
- A **registry** of playbooks. Each `agent/playbooks/<name>/` has a `config.yaml` (title, intent, lead role, tier;
  without a tier, the intent's tier from `config/tiers.yaml`) and a `graph.py` exposing `PLAYBOOK_SPEC`: input model,
  steps, gates, `flow(inputs)` for the timeline, `initial_plan(inputs)`, and an uncompiled `build(services)`.
- One **`RunState`** that every playbook extends (CODEWRIGHT.md 9.1): run/project ids, playbook, tier, validated
  `inputs`, workspace, profile, `limits`, plan, steps, artifacts (replaced by path when a step is reworked),
  approvals, feedback, budget and errors.
- **Tiered gates**: `plan_gate()` / `result_gate()` apply by tier (result from tier 1, plan from tier 2); tier 3
  playbooks add their own. A run may **raise** its playbook's tier, never lower it.
- The API compiles one graph per playbook with the shared `AsyncPostgresSaver` (`thread_id` = run id). Runs table
  (migration 0004): `inputs` (validated by the playbook's model), optional `project_id`, no `mode`.
  `GET /api/playbooks` describes steps, gates, input JSON schema and tier for the UI.

**Budgets** (`config/budgets.yaml`, `agent/llm/budgets.py`). Limits are resolved from the tier when the run starts and
stored in its state. `llm_step` checks them **before** each LLM step: tokens and LLM calls per step, tokens and hours
per run. When one is reached the run pauses with a `budget_exceeded` prompt: **continue** (every limit grows by its
base value once more) or **stop** (the run ends as cancelled). Usage is counted per step from the structured-output
results and, for agent loops, by a `UsageMeter` callback (`stream_usage=True`).

**Streaming** (implements ADR 0014). `astream(..., stream_mode=["updates", "messages", "custom"], subgraphs=True,
version="v2")`:
- LLM tokens (`messages`) are published to live subscribers only, as SSE `token` events without an id. They are not
  stored, so a reconnect doesn't replay them. Storing every token would cost a DB row per token for no later use;
  the full text is in the traces and the workspace files.
- Agent tool calls and results inside a node's namespace (`work:<id>` / `tools:<id>` for sub-agents) are stored as
  `agent_activity` events (the team activity feed).
- Plan, step, gate and status events stay as before (stored, then fanned out, `Last-Event-ID` resume).

**Limits for a 9B model** (found on the GPU):
- `schema_for` stripped every `title` key, which also deleted **fields** named `title`, so the grammar dropped a
  required field and every attempt failed. Only schema annotations are stripped now.
- An agent can loop (the read-only helper called `ls` again and again) until the request exceeds the 4K context
  (HTTP 400). Each agent invocation is now capped with `ModelCallLimitMiddleware(run_limit=..., exit_behavior="end")`:
  8 model calls for the lead, 6 per sub-agent. The step then checks what was actually written. The caps stay when the
  context grows.
- The Business Analyst once pasted the brief into its reply instead of writing it. The prompt now says that only the
  file counts; 3/3 later runs wrote it with `write_file`.
- A dead server took the full 600 s request timeout to notice. Model clients now use a 10 s **connect** timeout
  (`connect_timeout_s`); long generations keep the 600 s read timeout. A lost GPU now pauses the run in ~9 s.

**Remote GPU access.** The user keeps ngrok for now, **with authentication**: llama-server `--api-key-file`, the same
key in `REMOTE_GPU_API_KEY`. ngrok's basic auth would collide with the key (both use `Authorization`). The health check
now proves the setup: it calls a protected endpoint with the key (error if rejected) and, for a public URL, without it
(warning if the server answers anyway). Tailscale is documented as the long-term option (`docs/setup/remote-gpu.md`).

**`num_ctx`.** 4096 today, matching the server. Target 8K–16K: the largest context that leaves ≥ 1 GB of the 10 GB
free, measured with `scripts/measure_vram.py` (native Windows llama-server) or `scripts/measure-vram.sh` (Docker).

## Measurements (remote GPU, 2026-10-27)
| What | Result |
|---|---|
| Structured outputs (`evals/structured_output.py`, 42 cases) | 42/42 valid on the first try, 31/42 correct, 2.2 s and ~138 tokens per call |
| Sample playbook, plan + deepagents team | 5–6 LLM calls, ~6–7.6K tokens, 13–20 s per run; `brief.md` written 3/3 |
| Crash during a step (`docker compose kill api`, then `up`) | resumed from the checkpoint, re-ran the step, continued |
| GPU lost during the agent step | paused after ~9 s with retry / switch to CPU; retry finished the step |
| VRAM vs `num_ctx` | pending: table from the GPU machine |

## Consequences
- Adding a playbook is a folder plus one line in the registry; the API and the run screen work from its spec.
- Budget, GPU-loss and gate prompts share one `pending` + `answer` path, so the chat's approval cards (Phase 2) reuse it.
- Token events are lost on reconnect by design; chat replies in Phase 2 store the final message text instead.
- Follow-ups: fill in the VRAM table and raise `num_ctx` (server `-c` and Settings together); re-check the per-agent
  caps against real playbooks from Phase 6 on.
