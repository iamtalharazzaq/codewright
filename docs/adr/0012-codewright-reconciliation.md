# 0012. MonoShift becomes Codewright: rename and chat-first reconciliation

- **Status:** accepted
- **Date:** 2026-10-27
- **Phase:** 0

## Context
Phase 0 and most of a Phase 1 were built from an earlier spec, "MonoShift" (monolith → microservices only). The new
README (Codewright) makes the product a Claude-style chat app with 18 intents; microservices conversion is one playbook.
README Section 0.5 asks to reconcile the existing work. The user approved the proposed changes on 2026-10-27, with two
instructions: **no product name in `.env`**, and recreate the database from scratch.

ADRs 0001–0011 are kept unchanged as history. They use the old name, old README section numbers and the old
`MONOSHIFT_*` variable names; this ADR maps them.

## Decision
- **Name:** MonoShift → Codewright everywhere except historical ADRs. Python root package `codewright`, API package
  `codewright-api` / module `codewright_api`, web package `@codewright/web`, images `codewright-*`.
- **Environment variables lose their prefix**, so the product name never appears in `.env`:
  `MONOSHIFT_DATABASE_URL` → `DATABASE_URL`, `MONOSHIFT_LLM_REMOTE_GPU_URL` → `LLM_REMOTE_GPU_URL`,
  `MONOSHIFT_API_URL` (web build) → `API_URL`, and the same for every other `MONOSHIFT_*` key. `COMPOSE_PROJECT_NAME`
  is gone: `deploy/docker-compose.yml` sets `name: codewright`, and the Postgres user/database default to `codewright`
  there. Langfuse keys keep their own `LANGFUSE_*` names.
- **Data model** (migration `0003`): projects are any codebase, so `projects.mode` is dropped; runs get `playbook`
  (default `microservices`) and `tier` (0–3). `runs.mode` stays as the microservices playbook's variant until Phase 1
  replaces the run state with the README's `RunState`. The old dev database volume was removed (user-approved).
- **Existing Phase 1 work is kept**, committed as found, then renamed. `MonoShiftState` is now `WorkflowState`.
  Phase 1 reshapes it into the generic run/playbook pattern and moves the 10-step workflow into
  `agent/playbooks/microservices/`.
- **Structure** (README Section 13): added `agent/chat/`, `agent/playbooks/`, `templates/{apps,services,ci,deploy,
  frontend}/`, `evals/{repos,references,tasks}/`, `config/{tiers,budgets,noise_rules.default}.yaml`. Removed the empty
  `agent/language_advisor/` (the Language Advisor is a Solution Architect sub-agent, Section 6.1).
- **UI:** the dashboard frame is replaced by the chat shell (sidebar, chat, artifacts side panel). Projects, Runs and
  Settings stay as full pages under the `(pages)` route group.
- **Checks run in Docker** (user instruction: no GitHub CI for now): `make check` builds `api-checks` (ruff, mypy,
  pytest against a throwaway `codewright_test` database in the compose Postgres) and `web-checks` (ESLint, tsc,
  Prettier, Vitest). The GitHub workflow is kept for when a remote exists.

## Consequences
- Anyone with an old `.env` must rename the keys (the user's was migrated; a backup was kept outside the repo).
- Generic variable names (`DATABASE_URL`, `LOG_LEVEL`, `GITHUB_TOKEN`) can be picked up from the host shell when the
  API runs outside Docker. Inside compose only the listed keys are passed, so containers are unaffected.
