# 0016. Spec v2 reconciliation: CODEWRIGHT.md replaces README.md

- **Status:** accepted
- **Date:** 2026-10-27
- **Phase:** between 1 and 2

## Context
`CODEWRIGHT.md` is now the single source of truth; `README.md` (the first Codewright spec, itself a rewrite of the
MonoShift spec) stays unchanged as history. Phase 0 and Phase 1 were built under `README.md`. Phases 0–1, the harness
(Section 9), the LLM section (10) and the phase numbering are the same in both, so nothing built has to be redone.
What v2 adds:

- **C12** exactly 5 languages: C++, TypeScript, JavaScript, Go, Python. Others are declined with a suggestion.
- **C15/C18** confirm before making anything; always ask the language for anything new.
- **C17** architecture-agnostic: `convert_microservices` becomes `change_architecture` with six targets.
- **C19** skills (slash commands, custom skills, auto-use, import/export; Section 8.6, component 25).
- **C20** code review (`review_code`). 20 intents in total, with `write_code`, and `new_app` is tier 1–3 by size.
- Done card + verified `GUIDE.md` (3.5), live build graph (8.2), a larger template list (8.4), a benchmark set (15.0).
- Phase 5 builds all 5 Language Packs; Phase 6 adds review and skills.

## Decision
Applied now:
1. `CODEWRIGHT.md`, `EXAMPLES.md` and the updated `PROMPT.md` are committed; `README.md` is untouched.
2. `config/tiers.yaml`: the 20 intents. `change_architecture` (tier 2, max 3), `new_app` (tier 1, max 3), `write_code`
   (tier 1), `review_code` (tier 0, max 2 when fixes are applied). Missing-info limits (`clarifier`: 5 questions per
   round, 2 rounds).
3. The `microservices` playbook is now **`architecture_change`** with a `target` input (`microservices`, `modules`,
   `modular_monolith`, `merge`, `serverless`, `event_driven`). Only `microservices` exists (stub steps); the others are
   rejected with a clear message until Phases 15–17. A playbook can now raise its tier from its inputs
   (`PlaybookSpec.min_tier`): the microservices target runs at tier 3.
4. Section 13 folders: `agent/skills/`, `skills/builtin/`, `skills/user/`. Language Packs follow **C12**
   (`python`, `go`, `typescript`, `javascript`, `cpp`). Section 13 still lists `java/ php/ dotnet/`, which contradicts
   C12; C12 wins.
5. The chat's welcome suggestions come from `EXAMPLES.md`.
6. The user's choices that differ from the spec text stay: Docker-only checks (no CI run), tests at the end of each
   phase plus cheap per-feature tests, ngrok with an API key for now (Tailscale documented), `num_ctx` set from the
   VRAM measurement (target 8K–16K), per-agent model-call caps kept (ADR 0015).

Not applied: `README Section N` references in older code comments and ADRs stay as written. Section numbers moved
only for new sections, and rewriting history buys nothing. New code cites `CODEWRIGHT.md`.

## Benchmark candidates (Section 15.0, for the user to choose)
Not cloned until disk space is freed (6.3 GB free now). Before cloning, each will be checked for license, recent
activity and size; none is verified yet.

| Type | Language | Candidates |
|---|---|---|
| Server-rendered / API web app | Python | `wagtail/bakerydemo` (Django CMS demo) · `fastapi/full-stack-fastapi-template` (FastAPI + React) · a Django RealWorld API (`gothinkster` list) |
| Backend API | TypeScript | `lujakob/nestjs-realworld-example-app` (NestJS) · `gothinkster/node-express-realworld-example-app` (Express) |
| Frontend / API | JavaScript | `gothinkster/react-redux-realworld-example-app` (React) · an Express RealWorld API in plain JS |
| Console app / library | C++ (CMake) | `p-ranav/tabulate` (header library) · `CLIUtils/CLI11` (library) · `jarro2783/cxxopts` (small library + examples) |
| Frontend-only | TypeScript | `alan2207/bulletproof-react` · a Vite RealWorld frontend |
| CLI tool + library | Python / Go | `charmbracelet/glow` (Go CLI) · a small Typer-based Python CLI |

The RealWorld ("Conduit") family is attractive because the same app exists in several languages, which helps the
"two benchmarks of different languages" rule and later translate checks.

## Consequences
- `PROGRESS.md` follows `CODEWRIGHT.md`'s numbering (unchanged numbers).
- Phase 2's router reads 20 intents; skills (Phase 6) map slash commands to them.
- Open: the user picks the benchmarks; disk space must be freed before cloning.
