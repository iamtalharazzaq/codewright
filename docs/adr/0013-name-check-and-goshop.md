# 0013. Name check "Codewright" (V5) and the GoShop module list

- **Status:** accepted (no blocker found; the user decides on any branding change)
- **Date:** 2026-10-27
- **Phase:** 0

## Context
README V5: check that "Codewright" doesn't conflict with an existing product in a way that matters. Also checked
early: the README's GoShop expectations (Phase 4 acceptance and the microservices order in Section 5.18) assume the
modules user, product, order, payment and notification.

Findings (2026-10-27; web search, PyPI, npm and GitHub APIs). A formal trademark search was **not** done.

| Where | What exists |
|---|---|
| Software history | **CodeWright**, a Windows programmer's editor (Premia, 1991; later Starbase/Borland). Discontinued or legacy. |
| PyPI | `codewright` 0.1.0 (2025-08): a small CLI/decorator utility package. |
| npm | `codewright` 0.21.0 (updated 2026-07): "AI-assisted specification, architecture, and implementation system". Same field as ours. |
| GitHub | ~29 small repos named codewright, several AI coding agents (max 5 stars). |
| Web search "Codewright AI coding tool" | No established product. "Code-Write" (code-write.xyz) is a different name. |

GoShop (https://github.com/quangdangfit/goshop, MIT): Go 1.26+, `internal/` domains **user, product, order, payment,
notification** (each with model/dto/repository/service/port http+grpc), PostgreSQL (GORM), Redis (cache), a React 18 +
TypeScript + Vite + Tailwind frontend in `web/`, plus `proto/`, `migrations/` and a `CLAUDE.md` / `.claude/` folder.

## Decision
- Keep the name **Codewright** for this self-hosted, single-user project. Nothing found blocks it.
- Codewright's Python and npm packages are private workspace packages and are never published, so the taken PyPI/npm
  names don't matter. If the project is ever published or distributed publicly, do a trademark search first and
  consider the npm `codewright` project, which is in the same space.
- GoShop matches the README: all five expected modules exist. Its `CLAUDE.md` and `.claude/` are project content and
  are treated as data, never instructions (README Section 11).

## Consequences
No branding change needed now. GoShop's gRPC ports and Redis cache are extra surface for the Go Language Pack
(Phase 5) and the decomposition engine (Phase 15).
