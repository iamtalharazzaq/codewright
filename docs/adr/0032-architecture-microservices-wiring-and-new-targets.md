# 0032: Architecture change III: wiring the database split, and merge/serverless/event-driven

Date: 2026-10-29 · Status: accepted · Phase 17

## Context

CODEWRIGHT.md 5.18 and Phase 17: ADR 0031 built the microservices conversion but left two things unfinished. First,
`agent/microservices/data.py` — sagas, the database-split check/contract stages, `apply.sh`/`rollback.sh`,
`STAGES.md`, and rewriting the frontend's API addresses to the gateway — was written but never called from
`architecture_change`'s `db_split`/`frontend` steps, so a real conversion still only got the expand stage and never
touched the frontend. Second, ADR 0029 refused three targets up front — `merge`, `serverless`, `event_driven` —
"designed now, built later." This phase wires the first and builds the other three, following the house rule for
this playbook: mechanical, deterministic, small steps, each tested, undone exactly on red.

## Decision

1. **Database split, fully wired** (`agent/playbooks/architecture_change/microservices.py::db_split`). The step now
   writes the expand files (as before), the check/contract stage files and `apply.sh`/`rollback.sh`/`STAGES.md`
   (`data.stage_files`), and — when the design has sagas — the saga library plus its generated tests
   (`data.saga_files`), all merged into one commit. Only the expand files are run through `project.db_trial`, since
   check/contract assume the expand stage already shipped and the parity window has closed.
2. **Frontend against the gateway, fully wired** (`...microservices.py::frontend`). Alongside the existing
   `gateway_rewrite` call per frontend file, `data.gateway_routes_doc` now writes
   `docs/architecture/GATEWAY_ROUTES.md`, documenting which prefixes are live versus still answered by the monolith.
3. **Two real bugs in `data.py`, found by running its own output, not by reading it.** A saga that crashed before its
   first step had nothing in the store to resume from (`store.save` was never called on a fresh run) — fixed by
   saving the initial state immediately. The API-address regex matched `localhost` as an API hint via the substring
   `host`, defeating the documented "the frontend's own dev address is left alone" — fixed with a word boundary
   (`\bhost\b`). Both were caught by `agent/tests/microservices/test_data.py` actually executing the generated saga
   test file and the gateway-rewrite function, not by asserting on their text.
4. **`dbsplit.py`'s one-line fix confirmed.** The `saga_state` table's `CHECK` constraint already lists
   `'compensated'` among the allowed statuses in this worktree; no further edit was needed.
5. **`merge`, fully real** (`agent/microservices/merge.py`). The mechanical reverse of an extraction: detected
   straight from the working tree (the shim mark, the literal service name every shim's `call`/`acall`/`remote`
   argument names), not from the design, so a project merges cleanly however its services got there. Folds each
   shim's local code back, deletes the service's own copy and runbook, drops its gateway route and regenerates
   `nginx.conf`, and removes the anti-corruption layer once no shim calls anything through it. A service already cut
   over to 100% and `finalize`d has no local copy to restore, so merging it is refused with the reason, not guessed.
   Wired into `restructure()`/`report()` the same way `modules`/`modular_monolith` already were — no change to
   `graph.py`'s step sequence was needed, because the generic outcome shape (`title`/`kind`/`file`/`to`/`reason`/
   `done`/`note`) already fits `verify()` and the new `generic_comparison()`.
6. **`serverless`, real but scoped to Python** (`agent/microservices/serverless.py`). "Suitable" is mechanical: a
   backend design group with no table and no saga (`stateless_groups`). Reuses `extract.plan_extraction`'s entry-point
   analysis verbatim, but the apply side copies the group into `services/<name>/` with a handler per entry point
   (`event, context -> response`) and a deploy manifest template instead of an RPC router and a Dockerfile. The
   monolith's own copy is never touched — no shim, no cutover, no anti-corruption layer, because nothing calls the
   function remotely yet; wiring a real caller and trigger is a runbook, same as the canary cut-over in ADR 0031.
7. **`event_driven`, real but deliberately split into a safe half and a reviewed half**
   (`agent/microservices/event_driven.py`). The safe half is applied: an in-process pub/sub bus (`libs/events/bus.py`,
   swappable for a real broker later, same spirit as the event envelope in ADR 0031) and subscriber registration —
   both pure additions appended after the existing function, so they cannot change what it does when called directly.
   The unsafe half — rewriting the producer's call site from a direct call to a `publish()` — is not applied
   mechanically: whether the return value is used can't be reliably proven by AST alone, and a wrong rewrite changes
   behavior instead of just moving it. That half is a generated, human-reviewable doc
   (`docs/architecture/EVENT_REWRITE_REVIEW.md` via `review_doc`) naming the exact call sites and why each was left
   alone, matching the instruction to prefer no action over a guessed one.
8. **`CONVERT_TARGETS` extended** (`agent/playbooks/architecture_change/steps.py`) to include `merge`, `serverless`
   and `event_driven`; only `recommend` is refused for a direct conversion now (it exists to pick a target, not to be
   one).
9. **Reports extended, not rebuilt.** `report()` and `comparison()` already branched on `target == "microservices"`;
   a second branch now covers `mode == "conversion"` for the three new targets, backed by a new `generic_comparison()`
   that reads the same `outcomes` list every one of them produces, writing `COMPARISON.md` through the existing
   Deliver/output-connector machinery untouched.
10. `restore()` in `extract.py` (shared by `merge.py` via module-level aliasing) now re-creates a file's parent
    directory before writing it back, because `apply_merge` may have `shutil.rmtree`'d the whole folder a shim's
    local copy lived in.

## What this does not do

- `merge` is the one target built completely, per the scope given for this phase: a small multi-service fixture
  merged back into one app with 0 regressions is proven locally
  (`agent/tests/playbooks/test_architecture_merge.py`), driven through the real graph (gates, baseline, verify,
  report) with a fake sandbox and a fake replay.
- `serverless` never rewires a caller to invoke the packaged function, and never deploys the manifest — both are
  explicitly a human's runbook, same as ADR 0031's canary cut-over.
- `event_driven` never rewrites a producer's call site; the review doc names the work, it does not do it.
- The database split's check/contract stages, the saga library, and the gateway rewrite are now wired into the real
  flow, but — like ADR 0031's own database trial — were only exercised against `project.db_trial`'s fake in tests,
  never against a real PostgreSQL sandbox.
- The GoShop saga-paths-replay-with-0-regressions acceptance and the M4 demo (CODEWRIGHT.md 5.18) need a live run
  against the running stack through the API's single run slot. That was explicitly out of scope for this phase —
  it is left open, for the coordinating session to run.

## Consequences

A microservices conversion now leaves a database split with reviewable up/down SQL through every stage, a saga
library with its own passing tests, and a frontend pointed at the gateway with a routes doc — not just the
schema-expand step ADR 0031 shipped. A multi-service project can be folded back into one app mechanically, with the
same revert-on-red guarantee as every other step in this playbook. Two more targets — serverless packaging and
event-bus wiring — move from "designed, refused at conversion time" to "real for the safe, provably mechanical half
of the work," each leaving behind an explicit, reviewable account of the part that still needs a human.
