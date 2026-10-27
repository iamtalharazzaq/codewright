# 0009. Role agents with deepagents and per-role tool allowlists

- **Status:** accepted
- **Date:** 2026-10-26
- **Phase:** 1

## Context
deepagents 0.7 adds file system tools (`ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep`) and a
`task` tool to every agent, plus an automatic `general-purpose` sub-agent. Measured: their schemas total ~10.5K
characters (~2.6K tokens), and the stock `write_todos` tool adds ~5.7K more characters. The local server gives each
request 4096 tokens. Restricting tools is only exposed through private "harness profile" internals.

## Decision
- Each role has `agent/agents/<role>/prompt.md` and `config.yaml` (`name`, `description`, `tools`).
- `ToolAllowlistMiddleware` (public LangChain `AgentMiddleware` API) hides non-allowed tools from the model **and**
  refuses calls to them. Applied to the main agent and to each sub-agent.
- Planning uses `TodoListMiddleware` with a 1-line prompt and a 2-line tool description.
- The default `general-purpose` sub-agent is replaced by a read-only helper (`ls`, `read_file`).
- File system: `FilesystemBackend(root_dir=<workspace>, virtual_mode=True)`; a test confirms `/../` can't escape.

## Consequences
Measured on the CPU (Qwen3.5 9B Q4_K_M): Project Manager → `task` → Business Analyst → `write_file` → report worked
end to end and produced a correct `intake/notes.md`; 11.5K tokens over the conversation (8.2K served from the prompt
cache), **~20 minutes**. Agent loops are viable on CPU only for small tasks; most Phase 4–6 work should be single
structured calls (ADR 0007) with tools/algorithms doing the rest, and agent loops kept for the GPU.
