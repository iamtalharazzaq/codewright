# 0001. Record architecture decisions

- **Status:** accepted
- **Date:** 2026-10-26
- **Phase:** 0

## Context
README Section 0.2 requires every significant technical decision to be recorded. The building agent works one roadmap
phase at a time and must be able to explain later why something was chosen.

## Decision
Use lightweight ADRs in `docs/adr/NNNN-kebab-title.md`, numbered in order, based on `0000-template.md`.
An ADR is never edited to change its decision; a new ADR supersedes it. Open questions waiting on the user are listed in
`PROGRESS.md` and get an ADR once answered.

## Consequences
Decisions are reviewable in git history next to the code they affect.
