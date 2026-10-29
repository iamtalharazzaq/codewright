# 0033: Translate

Date: 2026-10-29 · Status: accepted · Phase 18 (playbook)

## Context

CODEWRIGHT.md 5.16 and 8.5: rewrite a CLI or HTTP-service component into another of the five languages, spec-first,
one function at a time, so a small model never has to hold the whole program in its head. Acceptance: a GoShop
service rebuilt in Python passes the same contract and replay tests; a small Python CLI translated to C++ passes
the same black-box tests.

## Decision

- **Only a CLI or an HTTP service is translated** (`TRANSLATABLE_KINDS = ("cli", "api")`). A library, a full-stack
  app and a browser frontend (Node's `"web"` kind — React/Vite, Next.js pages) are declined the same way: none of
  them has a single entry point to compare behavior at. Browser-frontend rewrites belong to Frontend modernize
  (5.14), not here.
- **Survey finds the units by rules, not by a model** (`inventory.py`): Python is parsed with `ast`; the other four
  languages use declaration patterns and brace matching. A unit's callees are translated before it, the entry point
  last, so each translated unit only ever calls names that already exist. `coverage` says how much of the source the
  units hold, honestly, rather than claiming full coverage of layouts the scan does not understand.
- **A CLI is proven with black-box cases, not unit tests**: the QA Engineer proposes invocations from the entry
  point, they are run on the original first (`blackbox.capture`), and only the stable ones (no crash, no hang)
  become the expectation. The same cases are then run on the translation (`blackbox.check`) — same arguments and
  stdin, same exit code and output, nothing about either language's internals. An HTTP service falls back to the
  target Pack's own tests, with the card saying plainly that request-by-request black-box comparison for services
  isn't implemented yet, rather than claiming a parity that wasn't checked.
- **Translation lands in a new folder, alongside the original** (`translated/<package>-<pack>/`), never over it:
  nothing in the running app is cut over, the original stays runnable (so black-box capture and check can both
  happen in the same project without stashing anything), and Deliver decides what, if anything, replaces the
  original later.
- **One file per translation** (`target.FileBuilder`): every surviving unit's imports are collected once and
  deduplicated, then the units follow in translation order. A single file means no cross-file imports for a small
  model to get wrong, at the cost of not scaling to very large components (`MAX_UNIT_CHARS` already skips a unit
  that wouldn't fit one call; a component with many such units gets a visibly partial translation, not a silent
  one).
- **The build is the Reflection loop** (`agent.playbooks.reflection`, shared with Write code): the assembled file is
  built in the sandbox; on failure, the whole file is rewritten from the compiler's own output, up to 5 tries. The
  same loop, the same budget bookkeeping, no new retry machinery.
- **The gates are the usual two**: approve the plan (target language, coverage, cases captured — the Language
  Advisor's recommendation is this gate itself, not a separate model call) and approve the result (build status,
  black-box line, Tech Lead findings), matching every other tier-3 playbook rather than inventing a third gate for
  translation specifically.
- **`BUILT_PHASES` in `agent/chat/intents.py` was left unbumped**, matching the precedent already set by
  Phases 15-17 (architecture_change): the natural-language chat router's notion of "built" phases is a separate,
  deferred decision from registering a playbook so `/api/playbooks` lists it. `translate_language`'s tier, intake
  and intent-label wiring were already in place before this phase; only the playbook registry entry was missing.

## Consequences

Verified locally: a small Python CLI (two units: a helper function and the entry point) translated to C++ and
checked against the same black-box cases, both with a fake sandbox and scripted model (`agent/tests/playbooks/test_translate.py`)
and against the real sandbox runner — a real `git` repo, the real Python original executed to capture cases, a real
CMake + Ninja build of the C++ translation, the real binary checked against those same cases
(`agent/tests/playbooks/test_translate_sandbox.py`, `pytest -m sandbox`). Both pass.

Not attempted, and left open: the GoShop-service-rebuilt-in-Python acceptance item needs a real project and a live
run on the GPU model; this phase does not create or drive one. The HTTP-service path has never been exercised
end-to-end (build + the Pack's own tests in the real sandbox) — only the CLI path has a real-sandbox test. Request-by-request
black-box comparison for HTTP services remains unimplemented, called out honestly on the result card rather than
built partially.
