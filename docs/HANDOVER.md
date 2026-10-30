# Handover prompt (2026-10-30)

Paste the block below into a new Claude Code session in `/home/ubuntu/codewright`.

```
You are continuing work on Codewright (/home/ubuntu/codewright). Read PROGRESS.md, CODEWRIGHT.md (phase list),
docs/E2E-CHECKLIST.md and docs/HANDOVER.md first. The repo is committed and clean on `main` (last commit: "chat: no Open
web view button on the Done card of a plain function or library"). Everything up to Phase 19 is built; Phase 20 (Evals) is
partly done. 552 backend tests, 42 web tests, ruff, mypy, prettier all pass; the full `make check-sandbox` passed earlier.

Working rules (from the previous sessions):
- Run Codewright checks in containers with `docker --context default ...` (the `default` engine holds the running stack;
  do not touch hiring-compass, heart-agent or infra containers). Mount source with -v to avoid rebuilding the checks image.
- Real sandbox for sandbox tests (`SANDBOX_TESTS=1`, `make check-sandbox`); scripted LLM replies only where a model call is needed.
- Build the missing feature first, one check pass at the end. Explain what/why/benefit before asking me to pick an
  architecture option. Smallest bounded slice per step; keep PROGRESS.md and docs/E2E-CHECKLIST.md updated; commit each change.
- Do not widen the sandbox gateway's port binding. The API never holds the Docker socket (sandbox-runner does).
- Pause and tell me if free disk drops below 15 GB (it is about 8.9 GB now: ask before `docker image prune -a`).

Finish, in this order:
1. Phase 20 (Evals) is built and was run live (numbers and findings in PROGRESS.md "Phase 20"). Next: the model-quality
   failures it found (JSX in .js files, Go/C++ write_code, the Go run that hung in verify), then re-run `make eval-nightly`.
2. Build quality for new_app: (a) verify must fail an app that does not implement the request (acceptance check, not just
   the template's sample tests); (b) the fix loop for TypeScript/JavaScript apps (tsc errors, tests that contradict the code);
   (c) why "Write a calculator app" with no platform answer picked the API template; (d) C++ function template (falls back now).
3. Phase 21 (Polish) and Phase 22 (Hardening, v1.0) per CODEWRIGHT.md.
4. Deferred earlier, documented in PROGRESS.md "known gaps": Phases 12 and 14 need live testing; Phase 16 red/undo/finalize/
   non-Python/DB split; Phase 10 upgrade for Go/C++ and db_change; Phase 15 TypeScript moves; Phase 13 model-driven nodes in
   the real sandbox; Phase 7 recorder/bench/screens.
5. Docker Desktop migration (I chose "Move everything to Docker Desktop"): not started. Needs more free disk first; export
   the Postgres data and the workspaces volume before moving; keep the other projects on the default engine untouched.
6. Merge-readiness against the parallel branch fix/qa-gate-and-dedup (it did not exist locally): fetch it and check for conflicts.

Report back with pass/fail of the full run and confirm the repo is clean and committed.
```

## State at the handover

- Latest features: Plan tab rows open an agent modal (received from / sent to / how it worked); "Which platform?" has
  "Just a function (one file, no library)" (function-python/ts/go templates); Done card has "Open web view" (not for functions);
  previews can carry a path (FastAPI apps open /docs); verify flags test code inside app source; deliveries leave out
  graphify-out and .codewright; no vitest when frontend tests are not ticked.
- Running stack was rebuilt at the last commit (api, web, sandbox-runner).
