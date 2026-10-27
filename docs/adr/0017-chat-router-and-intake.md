# 0017. Chat: rule-first router, one-call intake, message tree (Phase 2)

- **Status:** accepted
- **Date:** 2026-10-27
- **Phase:** 2

## Context
Phase 2 builds the chat: conversations, the Intent Router for 20 intents, the missing-info check with a mandatory
confirm card (CODEWRIGHT.md 3.4), the Answer playbook and the in-chat cards, on a 9B model with a 4K context.

## Decision
- **Rules before the model.** Slash commands and unsupported languages (C12) are decided by code, so they are always
  right and cost no model call. The model only classifies (one structured call, ~1.2-1.5 s); tiers come from config,
  raised by app size (new app 1-3) or target (microservices 3).
- **One intake call per round** returns the open questions and a draft confirm card. Code enforces what a small model
  may miss: the language question for anything new (C18), at most 3 other questions, two rounds, card length limits.
- **The chat's state lives in its messages.** A reply to open questions continues the intake; a typed "yes" on an open
  card starts it. So editing a message or regenerating a reply (siblings in a message tree, `head_id` = the branch
  shown) needs no separate state.
- **Runs stay simple in the chat** (user request): a small run card (status, steps, approve/reject, link); the run page
  keeps the details. A finished run posts a Done card through a run-status listener.
- **Streaming:** tokens are live-only SSE events; the final text is stored. Next.js response compression is off,
  because gzip buffered the proxied event streams.

## Consequences
- Router accuracy 118/121 on the eval set (EXAMPLES.md and more). Re-run `evals/router.py` when prompts change.
- Intents without a playbook confirm and then say which phase builds them; Phase 6+ plug playbooks in by name.
- Memory holds only the preferred language for now; project memory arrives with projects (Phase 3).
