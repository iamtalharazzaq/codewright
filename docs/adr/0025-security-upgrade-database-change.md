# 0025: Security review, Upgrade and Database change

Date: 2026-10-29 · Status: accepted · Phase 10 (Milestone M2)

## Context

CODEWRIGHT.md Phase 10: `security_review`, `upgrade` (5.11) and `database_change` (5.12). All three act on a
project's code or database, so each needs proof before it is offered for approval, and none may claim more than it
measured.

## Decision

- **security_review**: scan (secret patterns, the project's own security lint rules, dependency audit through the
  Language Pack: pip-audit, npm/pnpm/yarn audit, govulncheck) → model review of the scoped files (Security Engineer)
  → grounded findings (`review_core`). A pure review has one gate (result). A request that says "fix" is routed to
  tier 2 (plan first, then fix with the Reflection loop, tests, replay, and a rescan of the changed files).
  Any "fix" request escalates to tier 2 regardless of severity; a finer split would need findings at routing time.
  C++ has no dependency audit and Go has no gosec; the report says what was not covered.
- **upgrade**: the pack's `outdated` step lists direct dependencies (only those in the manifests); the plan names
  the packages the request mentions (to the version it mentions) or the safe same-major ones, max 4. Each upgrade is
  bumped by the pack, built and tested; while red, the files the errors point at are adapted by the model (3 rounds,
  `apply_steps(verify=False)`). An upgrade still red is reverted exactly. Every kept upgrade is its own commit.
  **Release notes are not read** (the sandbox has no web access); every brief says so.
- **database_change**: PostgreSQL family only. The next numbered `.up.sql`/`.down.sql` pair is planned, then really
  tried in a fresh sandbox database (`verification/dbtrial.py`): existing migrations (and seed data) applied, a
  snapshot (row counts, checksums, schema), the migration, a second snapshot and query plans, the rollback, a third
  snapshot that must equal the first. PostgreSQL's own error goes back to the model (Reflection loop, max 5). A
  migration that never passes is not committed. Changing engines (MySQL to PostgreSQL) is declined in the plan.
- **Plumbing**: `ProjectTools.run_step` and `db_trial`; `SandboxService.exec_step` and `db_trial`; pack methods
  `audit_steps`, `outdated_steps`, `upgrade_steps`; `vuln.go.dev` on the egress allowlist; pip-audit and govulncheck
  in the sandbox images.
- **Model connection**: the LLM client retries a connection dropped before any answer (3 extra tries). A tunnel to
  the GPU host was failing about 40% of single requests.

## Evidence (live, GoShop)

- Upgrade: two Go dependency bumps, two commits, 349 tests passing, replay 0 regressions in 25.
- Database change: index on `products.category_id`, applied to real PostgreSQL, rollback restored the exact starting
  state, plan Seq Scan to Index Scan on the measured query.
- Security: a seeded AWS key was found and removed, tests and replay green. The model also raised a false positive
  (`Delete` with an empty struct) and rewrote working code; the user sees it and approves or rejects at the gate.

## Consequences

Findings from the model are judgement, not proof; the approval gates are the control. Upgrade quality depends on the
tests the project has.
