# 0014. Streaming: LangGraph v2 stream parts to the chat (verification V3, streaming)

- **Status:** accepted (docs verified; Phase 1 proves it end to end)
- **Date:** 2026-10-27
- **Phase:** 0

## Context
The Codewright README adds **streaming** to V3: token-by-token chat replies and a live "team activity" feed of which
agent or sub-agent is doing what (Section 2.2). ADR 0004 covered sub-agents, file system, `interrupt()` and the Postgres
checkpointer, not streaming. Sources: docs.langchain.com, LangGraph "Streaming" and Deep Agents "Streaming", 2026-10-27.
Latest on PyPI: `langgraph` 1.2.18, `deepagents` 0.7.32, `langchain-openai` 1.7.3. Locked (14-day rule, ADR 0006):
`langgraph` 1.2.14, `deepagents` 0.7.24, `langchain-openai` 1.7.1. `version="v2"` stream parts exist since LangGraph 1.1.

Verified API facts:
- `graph.astream(input, config, stream_mode=[...], subgraphs=True, version="v2")` yields `StreamPart` dicts
  `{"type", "ns", "data"}`. `ns` is `()` for the root graph and `("node:<task_id>", ...)` inside subgraphs.
- Modes: `values`, `updates`, `messages` (`(message_chunk, metadata)`, with `metadata["langgraph_node"]` and `tags`),
  `custom` (anything sent with `get_stream_writer()`), `checkpoints`, `tasks`, `debug`.
- A model tagged `nostream` is not streamed in `messages` mode, which fits internal structured calls.
- Deep agents: with `subgraphs=True`, a sub-agent's events carry a namespace starting with `tools:<tool_call_id>`
  (spawned by the `task` tool); `updates` show `model_request` / `tools` steps and `__interrupt__`.
- LangGraph 1.2 / Deep Agents 0.6+ also offer a newer typed "event streaming" API (`stream_events(..., version="v3")`).
  The docs recommend it for new apps, but its documentation is thin so far.
- Live check against the user's remote llama.cpp through ngrok: an OpenAI-style `stream: true` request returns SSE
  deltas one token at a time (about 30–60 ms apart). The tunnel doesn't buffer.

## Decision
- Use `astream(..., stream_mode=["updates", "messages", "custom"], subgraphs=True, version="v2")`.
  - `messages` from the Project Manager's reply node → chat tokens.
  - `messages`/`updates` with a `tools:<id>` namespace → team activity (which role/sub-agent, which step).
  - `custom` → plan checklist updates, artifacts and progress events emitted by our own nodes and tools.
  - Internal structured-output calls are tagged `nostream`, so only user-facing text is streamed as tokens.
- The API keeps the existing pattern (ADR 0008): every event is stored, then fanned out over SSE with `Last-Event-ID`
  resume. Chat-turn events reuse it in Phase 2.
- Re-evaluate the typed event-streaming API in Phase 2, once it has stable docs. The v2 stream parts are enough.

## Consequences
One stream gives both the chat text and the activity feed. The Phase 1 spike must confirm token streaming through
`ChatOpenAI` to llama.cpp with `chat_template_kwargs` (thinking off), and the namespace shapes with the installed
versions.
