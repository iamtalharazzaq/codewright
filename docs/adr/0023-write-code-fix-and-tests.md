# 0023: Write code, Bug fix and Tests

Date: 2026-10-28 · Status: accepted · Phase 8

## Context

CODEWRIGHT.md Phase 8: `write_code` (5.1b), `fix_bug` (5.7) and `write_tests` (5.6) with the Reflection loop, a fresh
Tech Lead review, and tier 1 (confirm card first, one approval on the result). Before this phase, Write code was a
chat-only answer whose tests were never run. The model is a 9B model with a 4K context per request, so it cannot
patch a file, hold a long test file, or be trusted to hand back code it only saw part of.

## Decision

- **Every edit is the complete new content of one file** (`agent/playbooks/code_edit.py`), written by Codewright and
  diffed afterwards; the diff the user reviews is computed from the files, never taken from the model.
- **Codewright writes tests into its own file**, next to the project's (`test_x_codewright.py`, `x_codewright_test.go`,
  `x.codewright.test.ts`), and never rewrites an existing one: the model sees the first 3000 characters of a long test
  file and would silently drop the rest. The prompt lists the names already taken in the package and asks for
  `Codewright` in every new name (a Go package fails to compile on a repeated test name, which was the first live
  failure).
- **The Reflection loop** (`reflection.py`) is a plain bounded loop inside the node (max 5 attempts), not extra graph
  nodes, so each attempt still goes through `llm_step` (budget, model-server recovery). The feedback for the next try
  is what failed: the failing cases, plus the lines of the broken step's output that say why (compiler errors,
  assertions), because a build failure has no test cases at all.
- **Write code** needs no project: it builds the smallest project the language's Language Pack recognizes in a
  throwaway workspace (`scratch-<run id>`; `write_code/scaffold.py`), runs the tests in the real sandbox and returns
  code, tests, result and explanation. On attempts 3 and 5 it fixes the *tests* instead of the code, so a wrong test
  can't trap a right solution. In a project, the files are also committed on a `codewright/snippet-*` branch.
- **Bug fix**: locate (files and modules the report names first, then code search, source files only) → reproduce
  (a new test, run to confirm it fails; a test that doesn't even run proves nothing) → fix + verify (Reflection loop)
  → fresh Tech Lead review (same reviewer as `review_code`) → one approval → commit on `codewright/fix-*`.
- **Tests**: targets (the module the *request* names, else search hits restricted to source files) → write + verify per
  file, with coverage before and after → one approval → commit on `codewright/tests-*`. A test file that still fails
  after 5 attempts is **dropped and reported**, not committed: it would break the package for everyone.
- The Report tab now shows diffs and written code. Failed or dropped work is stated plainly on the approval card.

## Consequences

- Needs the sandbox runner and the Language Pack's test step for the language; without them the tests cannot run and
  Write code reports that honestly (no "passed" claim).
- Intake still asks questions before the confirm card (golden rule); a typed "yes" to the questions is an answer, not
  the confirmation.
- Quality is bounded by a 9B model: small functions in Python and Go pass in 1-4 attempts; a C++ example failed on a
  real API mismatch between code and tests. The eval set records these honestly (`PROGRESS.md`).
