# 0027: Frontend migration and modern UI

Date: 2026-10-29 · Status: accepted · Phase 12

## Context

CODEWRIGHT.md 5.14: rewire, migrate (React to Next.js first) with parity checks, then modernize with before/after
previews and accessibility checks. A 9B model with a 4K context cannot rewrite a component tree reliably.

## Decision

- **Migration is computed, not generated** (`frontend/migrate.py`). The existing `App` is rendered by a client
  component under one catch-all route (`ssr: false`), so every URL and browser-only API keeps working; title and
  description move to the layout, `VITE_*` env vars become `NEXT_PUBLIC_*`, the dev proxy becomes rewrites, and the
  test setup keeps Vite only when the tests use it. Anything that is not a plain React + Vite app is reported, not
  guessed. Moving pages to server components one by one is the follow-up, not part of this phase.
- **Modernization is rule-based** (`frontend/a11y.py`): a low-specificity design layer plus fixes the source can
  prove (WCAG 1.1.1, 1.4.3, 2.4.7, 3.1.1, 1.4.10). What needs judgment (labels, icon buttons, clickable `div`s) is
  listed. "Accessibility checks pass" therefore means: nothing left that the scan can see, with the rest named.
- **Parity** uses the Phase 7 `screens` verification (Playwright, pixel diff against accepted screenshots): baseline
  at survey, compare after the migration, re-baseline, compare again after modernizing (the before/after).
- Each stage is a commit; a stage whose build or tests fail is restored file by file.

## Consequences

Safe and boring by design; the redesign is limited to the design layer. Rewiring to a gateway (hard-coded API URLs)
is left to the architecture phases.
