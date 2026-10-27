# 0008. Run manager, gates and live events

- **Status:** accepted
- **Date:** 2026-10-26
- **Phase:** 1

## Context
README Phase 1: stub workflow with all 10 steps and 8 gates, Postgres checkpointer, gate API, live status via SSE,
resume after an API restart, and pause/ask when the GPU is lost.

## Decision
- **Workflow:** one LangGraph `StateGraph`; the per-service loop (Step 7 + Gate 5) is a compiled sub-graph. Edit and
  Reject at any gate route back to the step the gate reviews, with the comment stored in `feedback[step]`.
- **Gates** are nodes that only build a prompt, call `interrupt()` and record the answer, so re-running them on resume
  is side-effect free (ADR 0004).
- **GPU lost:** the LLM call happens inside the step; on `LLMUnavailable` the step calls `interrupt()` *outside* the
  `try` block and asks *retry* or *switch to CPU* (bounded to 5 rounds). The switch is written to state, so later steps
  use the CPU too. "Wait" is simply leaving the prompt unanswered: the run stays checkpointed.
- **Run manager** (in the API process): one background task per run, `AsyncPostgresSaver` on the MonoShift database
  (`thread_id = run id`), **one active run at a time** (409 otherwise). Statuses: created, running, waiting,
  completed, failed, cancelled. The open prompt is stored in `runs.pending`.
- **Restart:** on startup, runs left `created`/`running` are resumed from their checkpoint (or from the initial state
  if nothing was checkpointed yet). Shutdown cancels tasks without changing their status.
- **Events:** every event is stored in `run_events` and fanned out in memory; `GET /api/runs/{id}/events` streams
  stored events then live ones over SSE (FastAPI's built-in `fastapi.sse`), resumes after `Last-Event-ID`, and ends when
  the run ends. A health check of the run's model server is the first event of every run.
- **Traces:** every LLM call → `traces` (run, step, role, profile, tokens, latency, status). If `LANGFUSE_*` is set,
  the same record is also sent to Langfuse as a generation.

## Consequences
Single-process design: fine for one local user; a second API replica would need a shared event bus and locks.
