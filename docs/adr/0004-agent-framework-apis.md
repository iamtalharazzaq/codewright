# 0004. deepagents and LangGraph APIs (verification V3)

- **Status:** accepted (docs verified; a runnable spike is the first task of Phase 1)
- **Date:** 2026-10-26
- **Phase:** 0

## Context
README C8/V3: confirm current `deepagents` and LangGraph APIs for sub-agents, file system, `interrupt()` and the
Postgres checkpointer. Sources: docs.langchain.com (deepagents overview, subagents, backends; LangGraph interrupts,
persistence, checkpointers), PyPI, 2026-10-26.

Current versions (PyPI): `deepagents` 0.7.32 (needs Python ≥ 3.11), `langgraph` 1.2.17, `langchain` 1.4.7,
`langchain-core` 1.7.0, `langchain-openai` 1.7.2, `langgraph-checkpoint-postgres` 3.2.0. Several were released in the
last 14 days; the age rule (ADR 0006) will pick slightly older ones.

Verified API facts:
- **deepagents:** `from deepagents import create_deep_agent`; parameters include `model`, `tools`, `system_prompt`,
  `subagents`, `backend`, `middleware`, `permissions`, `memory`, `interrupt_on`. A planning to-do tool (`TodoListMiddleware`)
  and a `task` tool for sub-agents (`mode` `"isolated"` default or `"fork"`).
- **Sub-agents:** dicts with required `name`, `description`, `system_prompt` (isolated mode), optional `tools` (inherits
  the main agent's by default) and `model`; or `CompiledSubAgent` wrapping a compiled graph with a `messages` key.
  A default `general-purpose` sub-agent is added unless one with that name is supplied.
- **File system backends:** `from deepagents.backends import StateBackend, FilesystemBackend, StoreBackend,
  CompositeBackend`. `FilesystemBackend(root_dir=<absolute>, virtual_mode=True)`. The docs warn that
  `virtual_mode=False` gives **no** path restriction.
- **LangGraph HITL:** `from langgraph.types import interrupt, Command`. `interrupt(payload)` (JSON-serializable)
  pauses; resume with `Command(resume=value)` on the same `thread_id`. Needs a checkpointer. **The node restarts from
  the top on resume**, interrupts match by index, don't wrap `interrupt` in try/except, and side effects before an
  interrupt must be idempotent.
- **Postgres checkpointer:** package `langgraph-checkpoint-postgres`; `from langgraph.checkpoint.postgres import
  PostgresSaver` (async: `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`); `from_conn_string(...)`, then
  `.setup()` once. `thread_id` < 255 characters.

## Decision
- Gates are **dedicated LangGraph nodes** that do nothing but `interrupt()`, so re-running the node on resume has no
  side effects. Gate decisions are written to the `approvals` table by the API, then the run resumes with `Command`.
- Role agents use `create_deep_agent` with `FilesystemBackend(root_dir=<workspace>, virtual_mode=True)`, always
  `virtual_mode=True`, plus an explicit per-role tool allowlist (`tools=`) so isolated sub-agents never inherit tools by
  accident. The default `general-purpose` sub-agent is replaced so it cannot widen any role's tools.
- `AsyncPostgresSaver` on the MonoShift Postgres, with `thread_id = run id`.
- Phase 1 starts with a spike (fake chat model): a run pauses at a gate, the process is killed, and the run resumes
  from Postgres. Any API difference found there amends this ADR.

## Consequences
The workflow design in README Section 7 holds as written. `interrupt_on` (tool-level approval in deepagents) is
available if a role ever needs per-tool approval.
