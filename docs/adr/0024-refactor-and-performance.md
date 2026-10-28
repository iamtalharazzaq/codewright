# 0024: Refactor and Performance

Date: 2026-10-28 · Status: accepted · Phase 9

## Context

CODEWRIGHT.md Phase 9: `refactor` (5.9) and `improve_performance` (5.10), tier 2 (approve the plan, then approve
the result), with before/after graphs and benchmarks and 0 replay regressions. Both change a project's code toward a
goal the model itself decides the steps for, which is riskier than Phase 8's targeted fixes, so both need a second
gate before anything is touched, and proof afterward that behavior did not change.

## Decision

- **`change_core.py`** is shared by both: `apply_steps` makes a `ChangePlan`'s file-by-file changes one at a time,
  each a complete rewrite (same rule as Phase 8), tests it with the Reflection loop, and **undoes** (restores the
  original bytes) any step that never gets green — the branch a user approves is always a working one, never a
  half-applied plan. `behavior_check`/`baseline_recording` wrap the Phase 7 replay so "unchanged behavior" is a real
  replayed comparison, not a claim.
- **Refactor**: map (scope, dependencies, baseline tests, a traffic recording made or reused) → plan (Tech Lead
  proposes ≤4 changes, filtered to files actually in scope — no invented files) → **approve plan** → refactor →
  verify (tests, replay, before/after dependency graph) → review (fresh Tech Lead) → **approve result** → publish
  on `codewright/refactor-*`.
- **Performance**: baseline (benchmark the recorded traffic with k6) → find (the slow endpoints' code, plus a
  static scan for the usual causes — a query in a loop, a sleep, a list rescanned, reading everything at once) →
  Tech Lead plans fixes → **approve plan** → optimize → verify (tests, replay, benchmark again) → review →
  **approve result** → publish on `codewright/perf-*`. The verdict never claims a gain it cannot measure.
- **Live finding:** benchmarking GoShop for real showed every endpoint failing under k6's load, regardless of what
  was seeded — not a Codewright bug, but GoShop's own per-IP rate limiter (`pkg/middleware/ratelimit.go`, 100
  req/min) throttling the benchmark's own traffic (k6's virtual users share one source IP). Gin is configured with
  `SetTrustedProxies(nil)`, so spoofing `X-Forwarded-For` to dodge it is not available — correctly so: that would be
  bypassing the target's own protection, not benchmarking it. The fix is **honesty, not a workaround**: `_bench` now
  treats a benchmark where `failed_rate` is past 50% as *not measured* ("likely a rate limiter guarding against
  bursts like this"), the same as "the app could not be started" — never a flat, meaningless p95 reported as real.
- Seeding a slowdown under GoShop's response cache (`pkg/product`) or behind mismatched replay auth tokens
  (`wishlist`) hides it from the benchmark the same way; an uncached, unauthenticated endpoint (`ListCategories`)
  is what a live demo needs.

## Consequences

- Live-tested on GoShop: **Refactor** on `pkg/utils` (4 files, 349 tests green, replay 0 regressions/25 requests,
  committed). **Performance** on a seeded `ListCategories` delay: found and removed from the code alone, tests
  green, replay 0 regressions, speed correctly reported as *not measured* (the rate limiter), committed.
- A real benchmark number for GoShop needs either raising `RATE_LIMIT_REQUESTS` for sandbox-only testing or fewer
  virtual users; Codewright will not disable a project's own protection to get one.
- `apply_steps`' "undo the step, keep going" means a partial plan can still finish as a smaller, honest result; the
  brief lists what was skipped and why.
