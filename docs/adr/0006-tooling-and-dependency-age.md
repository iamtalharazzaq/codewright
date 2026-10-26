# 0006. Repository tooling and the 14-day dependency age rule

- **Status:** accepted
- **Date:** 2026-10-26
- **Phase:** 0

## Context
MonoShift runs untrusted code analysis on the user's machine and holds tokens, so supply-chain risk matters. Freshly
published package versions are the usual vector for compromised releases.

## Decision
- **Python:** one uv workspace (`pyproject.toml` at the root, members under `apps/`), Python 3.12, `uv.lock` committed.
  `[tool.uv] exclude-newer = "14 days"` ignores distributions uploaded in the last 14 days. ruff (lint + format), mypy
  (strict), pytest.
- **Web:** pnpm 12 (via corepack or `npm i -g pnpm@12.12.1`), `minimumReleaseAge: 20160` (14 days) in
  `apps/web/pnpm-workspace.yaml`, exact versions for direct dependencies, `pnpm-lock.yaml` committed. ESLint
  (eslint-config-next), Prettier, `tsc`, Vitest. TypeScript 6.0 (typescript-eslint doesn't support 7 yet).
- **Images and CI actions:** pinned tags at least 14 days old.
- **Exception:** a version newer than 14 days is allowed only to fix a published security advisory. It is listed in
  `minimumReleaseAgeExclude` / `exclude-newer-package` with the advisory IDs.
  - 2026-10-26: `next` 16.4.0 → **16.4.1** for GHSA-2464-fhr4-w9xw and GHSA-673q-mjm6-r5xr (critical RCEs) and
    GHSA-p3m5-59mp-jv5r (high DoS). The Next.js build itself refuses to run on 16.4.0.
- CI runs `pnpm audit --prod` and `pip-audit` so new advisories fail the build.

## Consequences
New releases are adopted with a short delay. Security fixes bypass the delay in a visible, documented way.
