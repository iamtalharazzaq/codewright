# 0031: Architecture change II: building the microservices

Date: 2026-10-29 · Status: accepted · Phase 16

## Context

CODEWRIGHT.md 5.18 and Phase 16: after the To-Be design (ADR 0029) the conversion builds the services: a foundation
(gateway, broker, auth, CI), then per service spec → scaffold → extract → anti-corruption layer → tests → replay →
review → PR → canary cut-over, in parallel where services are independent, then the database split and the frontend.
The conversion steps of `architecture_change` were simulated stubs. The model is small, so it cannot move a module
group into a service by rewriting files, and a cut-over that cannot be undone is not acceptable.

## Decision

1. **Mechanical extraction, Python only** (`agent/microservices/extract.py`). The functions other modules use are
   found by AST; the group's files are copied at the same dotted paths into `services/<name>/src/<name>_service/`
   (scaffolded from the Language Pack's API template), with an RPC surface `POST /rpc/<module>/<function>`.
   Blocked, with a stated reason: names that are not functions, star imports, dependencies on groups not extracted
   yet (or named as shared libraries by the user: `shared: util`), and non-Python code. Go, TypeScript and C++
   services are scaffolded and their code stays in the monolith until a compiler-based extraction exists.
2. **Anti-corruption layer as shims.** The monolith keeps its function names; each becomes a shim that calls the
   service by `CUTOVER_PERCENT_<SERVICE>` (0 = the local copy, kept as `_local_<stem>.py`), falls back to the local
   copy on a transport error below 100%, and has shadow and loopback modes for comparing answers. Arguments and
   results must be JSON-serializable; a service exception surfaces as `ServiceError`.
3. **All-or-nothing per service.** Tests and the recorded-traffic replay run after the extraction; on red the bounded
   reflection loop may repair files inside the service folder (at most 3 attempts); if still red, every file is
   restored and the service is `undone`. `finalize` (typed at Gate 5) removes the local code, flips the gateway route
   to live and is itself undone if the tests or replay fail.
4. **Foundation as templates plus static checks** (`foundation.py`): nginx gateway rendered from `routes.json`
   (everything still goes to the monolith: Strangler Fig), compose with pinned images and required secrets, NATS,
   Jaeger, PostgreSQL, the event envelope and a JWT check in Python/Go/TS, a CI matrix per service. Checked
   statically, never built.
5. **Scheduling** (`schedule.py`): waves, callees first, least coupled first, capped by `max_parallel`. Only the
   service-folder-only work (specs) runs concurrently; every change to the monolith is sequential, because they share
   one working tree.
6. **Database split as reviewable SQL** (`dbsplit.py`): schema and `NOLOGIN` role per service, tables moved with a
   compatibility view, cross-service foreign keys dropped, outbox / processed-events / saga-state tables, down
   migrations in reverse. Tried up-then-down with `project.db_trial` when a PostgreSQL sandbox exists, otherwise
   reported as not tried.
7. `simulate=True` keeps the stub flow unchanged; the real flow is used for `target=microservices, mode=conversion`.

## What this does not do

- No image is built and nothing is started: the sandbox has no Docker daemon. The canary (shadow → 10 → 50 → 100%)
  is configuration plus a runbook per service (`docs/runbooks/cutover-<service>.md`), applied where services run.
- The gateway does not verify the JWT; only the per-service library exists.
- Graphify per service is the template's `GRAPHIFY.md` and MCP example plus the project graph refresh.
- Shadow, replay against a running service and the database trial on real PostgreSQL were not run in tests.
- The frontend step only points the frontend at the gateway; redesign is the Modernize UI playbook.

## Consequences

A conversion of a Python monolith yields reviewable, individually revertible commits and a state in which the
monolith behaves as before (cut-over 0%). Other languages get scaffolds and an honest "not extracted" until Phase 18.
