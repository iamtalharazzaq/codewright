# 0011. Langfuse stays optional; the built-in trace store is the default

- **Status:** accepted (the user chose to keep Langfuse, 2026-10-26)
- **Date:** 2026-10-26
- **Phase:** 1

## Context
README: "Built-in trace view (every LLM/tool call stored in Postgres). Optional self-hosted Langfuse profile."
Langfuse v4 self-hosting needs 6 containers (web, worker, Postgres, ClickHouse, Redis, MinIO) and several GB of disk.

## Decision
- The built-in trace store (ADR 0008) is always on and powers the run view's "LLM traces" tab.
- Langfuse is an opt-in compose profile (`deploy/docker-compose.langfuse.yml`) that auto-creates the MonoShift project
  and API keys from `.env` on first start. When `LANGFUSE_PUBLIC_KEY/SECRET_KEY/BASE_URL` are set, each LLM call is
  also sent to Langfuse as a generation. Failures to reach Langfuse never break a run.
- What Langfuse adds over the built-in view: cross-run search and filtering, latency/token dashboards per task type,
  datasets and scores for evals (Phase 15), prompt versioning and side-by-side comparison of prompt changes.

## Consequences
Not started on this machine yet: the disk has ~5 GB free, not enough for the Langfuse images.
