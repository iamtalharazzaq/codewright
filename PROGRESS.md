# Codewright progress

Spec: **`CODEWRIGHT.md`** (v2, single source of truth since 2026-10-27; `README.md` is kept as history). Phase numbers
follow `CODEWRIGHT.md` Section 15.

**Current phase:** Phases 11-18 built and live-verified to varying degrees (see below); Phase 8's 20-example eval ran
2026-10-29; Phase 19 (deepen the Language Packs) started 2026-10-29, see its section below.
Still open: Phase 1 VRAM table, Phase 11's price-alerts acceptance, Phase 13's TypeScript reliability. Phase 16's
Python extraction path is now live-verified clean; Go extraction is out of scope by your call.
**Last updated:** 2026-10-29
**Branch:** `codewright-phase-0`

**Infra outage found and fixed 2026-10-29** (ADR 0034): the `codewright_default` Docker bridge network stopped
carrying inter-container traffic for over an hour — `api` couldn't reach `postgres`/`sandbox-runner`/`web`, so its
startup migration timed out every attempt and `restart: unless-stopped` crash-looped it the whole time; the
entire live app (chat, runs, graph, every playbook) was down. No subnet clash or VPN found; likely Docker's
bridge iptables rules going stale under heavy container churn, not fully pinned down (no host root to inspect
`iptables` directly). Fixed with your go-ahead: `pg_dumpall` backup taken first (`backups/`, gitignored), then
`docker compose down` (no `-v`, so `codewright_pgdata`/`codewright_workspaces`/etc. were untouched) and
`docker compose up -d --build --wait`. Confirmed working afterward: inter-container TCP all succeed,
`/api/health/ready` all green, a real chat round-trip through the remote GPU, and a live `write_code` run that
wrote code, passed 12 tests in the real sandbox, and reached its approval gate (then cancelled as a throwaway
check). Also hardened `apps/api/entrypoint.sh` so a future outage like this degrades visibly instead of
crash-looping: retries the startup migration up to 10 times with backoff, then sleeps with one clear fatal log
line instead of exiting. **`make check` re-run clean after the fix**: `check-api` (ruff, mypy, pytest) 508
passed/16 skipped (sandbox tests, need `make check-sandbox`); `check-web` (eslint, tsc, prettier, vitest) 24
passed — caught and fixed one unrelated Prettier formatting miss in `drive-card.tsx` along the way.

**Verification policy (changed 2026-10-29):** Codewright isn't bound to GoShop or any other single benchmark repo.
Every feature is verified with small, generic fixtures (tiny Python/TypeScript/JavaScript/Go/C++ projects) plus
automated tests — never tuned to one repo or domain. GoShop-specific acceptance steps, UI review passes, the Phase
6 audit review and the M1 demo are all **deferred to your own final end-to-end pass** rather than chased mid-phase.
`docs/E2E-CHECKLIST.md` collects manual test steps (what to do, what to expect) per feature, updated as each one
finishes; every phase section below links to its entry there. Benchmark-repo selection (ADR 0016) is deferred the
same way, until you're ready for that final pass.

## Resume here (written 2026-10-29)

Two sessions worked this branch back to back: one kept live-running Phases 11-13 in the background until its process
died mid-sweep (its last report was lost, exactly as expected — everything it did is still in the git log and
`/api/runs`); a second session (this one) picked up from there, live-ran Phases 14-15, finished and merged Phases 17
and 18, fixed a real Reflection-loop bug it found live, and ran the Phase 8 eval. Details:

1. **Phase 11 (add_feature):** still not clean. ~15 live attempts at "price alerts" on GoShop since the last session,
   every one that reached `build` either failed to compile or got cancelled before `review`. Two *other* feature
   requests completed, but one of them (`pin note`) silently wrote nothing ("file too long to rewrite safely in one
   go") while still reporting `completed` — a soft failure, not a real pass. The acceptance item (a price-alerts run
   that passes the migration gate and is approved) is still open; this looks like a 9B-model capability limit on
   Go type-correctness for a layered feature, not a playbook bug.
2. **Phase 12 (frontend_modernize, devops_deploy):** ✅ both now confirmed live.
   `frontend_modernize`: 4 live runs on a React+Vite todo app; the first 3 each failed a different way (`npm ci` on a
   stale lock, a missing `@types/node`, and `next/dynamic` assuming `App` is the default export); fixed in
   `agent/playbooks/frontend/migrate.py` (commit `fd2f0fd`) and the 4th run went fully green. `devops_deploy`: first
   live run ("Dockerize this app and set up CI") generated 3 files, all checks passed, committed — Phase 14 had zero
   live runs before this.
3. **Phase 13 (new_app):** ⚠️ not reliable yet. Multiple TypeScript tic-tac-toe attempts, three different failures:
   an empty model plan reported as "tests passed" (now guarded against, commit `eb7872e`), and twice the same
   root cause — a generated `useCallback` handler named identically to an imported pure function, shadowing it, so
   `tsc` rejects the component. Found and fixed a systemic gap behind this: the build-time Reflection loop
   (`agent/playbooks/feature/graph.py::run_tests`, shared by `feature` and `new_app`) only ran the test runner, never
   lint/`tsc` — and Vitest/Jest transpile with esbuild/Babel without type-checking, so a real type error could pass
   every build round and only surface later at `verify`, with no fix round left to use it. Fixed in commit `a39b3cd`
   (now checks `project.lint()` too, after tests pass). Confirmed live: the fix does make the build loop see and
   attempt the error now (previously it silently missed it); the 9B model still couldn't resolve this particular
   shadowing bug within the round budget, so the run correctly stayed red instead of silently passing. TypeScript
   apps with non-trivial state updaters are not yet reliable with this model — real, not a playbook bug.
4. **Phase 14 (devops_deploy):** ✅ see Phase 12 above — first live run clean.
5. **Phase 15 (architecture_change):** ✅ live-run on GoShop, `target=recommend`, `mode=audit`, real model call, all
   gates walked through by hand: 27 modules, 93 dependencies, 0 cycles → recommended **"Clean modules / layers"**,
   explicitly declining microservices ("the modules are too entangled to split cleanly today"), with scored
   alternatives. Design-only, nothing in the project changed, report delivered. Matches the spec's acceptance wording.
6. **Phase 16 (microservices build):** ⚠️ live-ran once, on `notes-api-python` (GoShop is Go, and real extraction is
   Python-only, so it can't exercise this phase — explained up front, not asked). The run completed all 5 gates
   (intake → as-is → design, 2 groups, score 15/100 → languages, both stay Python → delivered on a branch) but the
   `foundation` step reported "Adding the foundation changed behavior (tests or replay failed), so it was undone."
   Root-caused: not a real regression. The project's newest recording (made the day before, by an earlier
   session) had gotten **503 on every single request** — the recorder had raced the app's own startup — and
   `baseline_recording()` reused it unconditionally as "the baseline" without checking it was ever healthy. Today's
   normal 200/401 replies against yesterday's all-503 baseline were flagged as 16 regressions across 6 exchanges,
   and the undo-on-red logic (correctly, given that input) threw away a good foundation commit. This was a bug in
   the shared Phase 7 behavior-check path (`agent/playbooks/change_core.py::baseline_recording`), not specific to
   microservices — `refactor`, `performance` and any other `change_core` caller were equally exposed. Fixed: a
   recording where `server_errors + unanswered` covers the whole thing is no longer reused; `baseline_recording`
   falls back to an older usable recording, or records fresh. Commit `ef77fa0`, with `test_change_core.py` (3 tests).
   Deployed to the live `api`. Not re-run live after the fix (would cost another full GPU pass for a now-understood,
   already-fixed bug); the acceptance criterion itself ("all GoShop services extracted, 0 regressions, monolith
   serves nothing") stays open regardless, since Go extraction doesn't exist yet.
7. **Phases 17 and 18:** both finished, independently verified, and merged (commits `0810de7`, `b2f808b`; merges on
   `codewright-phase-0`). See their own sections below. ADRs 0032 and 0033.
8. **A harness bug, found and worked around, not fixed:** the LangGraph checkpointer's Postgres connection has no
   auto-reconnect after the connection drops — a stray `docker compose run` recreating the shared `postgres`
   container (my mistake, while spot-checking a worktree agent's tests) broke `/api/runs` until `api` was restarted.
   Health checks reported `ok` the whole time (they open a fresh connection per check), masking it. Worth a real fix
   in Phase 22 hardening (Phase 1 built exactly this resilience for the LLM client; the checkpointer connection has
   none). One live run (`fc9186c2`) was lost to this and had to be redone.
9. **`make check` (Step 5), run clean 2026-10-29:** `check-api` (ruff, format, mypy, pytest) and `check-web`
   (eslint, `tsc --noEmit`, prettier, vitest) both pass — 500 passed/16 sandbox-only-skip on the API side, 24 passed
   on the web side. Along the way, fixed the 9 remaining ruff/mypy issues (down from the ~20 noted earlier; other
   fixes this session had already cleared most). One was a real bug, not just lint: `new_app`'s `review_node` did
   `f.file`/`f.title` on `secret_findings()` results, which are plain `dict`s — this would have raised
   `AttributeError` any time a `new_app` build actually wrote a hard-coded secret, instead of reporting it. Fixed to
   dict access (commit `6b0bf95`). Also fixed `evals/write_code.py`'s own docstring (`-m evals.write_code`, not
   `evals/write_code.py`, the bug noted during the Phase 8 eval). The merged Phase 17/18 worktrees were removed
   (`.claude/worktrees/agent-ac3e31265f6dacd46`, `-af860f2ce22f19a0a`, both confirmed `git branch --merged` first)
   along with this session's throwaway tagged images (`:spotcheck`, `:p12`, `:p14`, `:p17`, `:p18`). **Caution for
   next time:** running `pnpm` in a container with the whole `apps/web/` bind-mounted (instead of just the one file
   needed) re-triggers a full `pnpm install` into the mount, writing root-owned `node_modules` onto the host and
   briefly costing ~700MB on a disk that's already at 96% — happened once this session, caught and removed via a
   throwaway `alpine` container (host `rm` can't touch root-owned files without sudo). For a one-file formatting fix,
   bind-mount only that file into the already-built checks image; never mount all of `apps/web`.

Next: Phase 19 (deepen the 5 Language Packs/templates), then 20 (evals), 21 (polish), 22 (hardening, v1.0).
Disk: 11GB free (96% used) — still don't prune Docker volumes or build cache without asking.

## Retrofit: real-sandbox playbook tests (started 2026-10-29)

A cross-cutting effort, separate from the phase numbering above: every playbook's existing tests run against
`FakeProject`/`FakeServices` (a fully mocked toolchain); the retrofit swaps the real pipeline in for the pieces
that actually touch a toolchain (build/test/lint), using the shared `agent/tests/sandbox_harness.py::RealProject`
(the real sandbox runner) and `agent/tests/cassette.py`/scripted replies for the model, so a test proves the
pipeline and the sandbox for real while staying fast and repeatable. Fast tests stay in `make check`; the
real-sandbox ones are `pytest.mark.sandbox`, gated behind `SANDBOX_TESTS=1` (`make check-sandbox`). Order agreed:
Phases 8, 9, 10, 11, 17 (real sandbox, all 5 languages) → 7 and 18 (repeatability, more language pairs) →
12/14 (live) → 4, 6, 13, 15, 16.
**Paused here 2026-10-29 at your request** (pace/token use) — Phase 8, 9 and 10 done; 11, 17 and the rest of the
order above not started. Resume when you ask.

- **Phase 8: real-verified on all 5 languages, all three playbooks** (commits `6e0bdcd`, `f00cd45`, `b630d0d`).
  - `write_code` (`agent/tests/playbooks/test_write_code_sandbox.py`). Found and fixed a real bug in the
    process: the TypeScript scratch scaffold's generated `tsconfig.json` had no `skipLibCheck`, so
    `tsc --noEmit` failed on `vitest`/`vite`'s own `.d.ts` files (missing `@types/node`) before ever reaching
    the user's code — this is almost certainly the same issue the Phase 8 eval above saw and didn't chase
    (`#15 Trie, TypeScript`: `Cannot find name 'setImmediate'`). Fixed in
    `agent/playbooks/write_code/scaffold.py`.
  - `bug_fix` (`agent/tests/playbooks/test_bug_fix_sandbox.py`) and `tests`
    (`agent/tests/playbooks/test_tests_sandbox.py`). Both rely on `own_test_file()`
    (`agent/playbooks/code_edit.py`) to place Codewright's own test file next to the source it's testing, which
    the mini-app fixtures didn't pick up (Python's `testpaths`, C++'s explicit test source list) — fixed first
    (commit `f00cd45`: `testpaths = ["."]`, a `CONFIGURE_DEPENDS` glob for the C++ test target). `bug_fix` then
    reproduces, fixes and commits the shared `avg()` off-by-one bug (every mini-app fixture has the exact same
    one, uncovered by its existing tests — handy, consistent real material); `tests` writes and verifies a new
    characterization test for `word_count`'s untested empty-string case.
- **Phase 9: real-verified on all 5 languages, both playbooks** (commits `3d78afc`, `5a58ff3`).
  `refactor` (`test_refactor_sandbox.py`): a behavior-preserving rename, verified with real tests; the
  behavior replay is honestly "not checked" (these fixtures are libraries, no runnable app to record traffic
  against). `performance` (`test_performance_sandbox.py`, reuses refactor's fixtures): finds its target via
  real code search (no DB/sleep code in the fixtures to trip the static smell-scan), fixes it with a real
  test-verified rewrite, and honestly reports the benchmark as "not measured" for the same reason.
- **Phase 10: real-verified on `security` (all 5 languages) and `upgrade` (TypeScript only); `db_change` deferred.**
  `security` (`test_security_sandbox.py`): a real secret/dependency/lint scan finds a planted fake AWS key, a
  scripted fix removes it, a real rescan and real tests confirm it; all 5 languages pass (~113s, real
  `pip-audit`/`npm audit`/`govulncheck` network calls). `upgrade` (`test_upgrade_sandbox.py`, TypeScript only —
  building a safe "really outdated" fixture per registry for all 5 languages is a lot of fixture upkeep for the
  same proof, and Python/Go/C++ fixtures have no real dependencies to upgrade yet) bumps a real outdated `lodash`
  pin via real `npm outdated`/`npm install`, verified by real tests, committed on its own branch. Found and fixed
  two real bugs along the way:
  - `agent/playbooks/upgrade/outdated.py::parse_outdated` dispatched on `pack == "node"` to pick the Node/npm
    `outdated --json` parser, but a Node/TS component's real `Component.pack` is always `"typescript"` or
    `"javascript"` (there is no `"node"` pack) — every real upgrade survey silently found zero outdated Node/TS
    dependencies. The existing fake-mocked unit test never caught this because it called `parse_outdated("node",
    ...)` with that same wrong literal directly. Fixed the dispatch to check `pack in ("typescript",
    "javascript")`; fixed the unit test's literal too (`test_upgrade_db_playbooks.py`).
  - `agent/tests/sandbox_harness.py::start_session` only ran `git init`, never an initial commit, so every
    fixture started with nothing tracked. `upgrade`'s own change detection (`_dirty()` in `graph.py`, `git diff
    --name-only HEAD`) only reports tracked files — with no HEAD it was always empty before *and* after a real
    bump, so the upgrade commit step silently committed nothing (and this stayed hidden, since the other
    retrofit tests detect "changed" files a different way). Fixed by committing the fixture as a baseline right
    after `git init`, matching how every real imported project already arrives with committed history.
  `db_change` is not retrofitted: `RealProject.db_trial()` is an honest "not available in the real-sandbox
  retrofit harness" stub (no scratch Postgres wired into this harness) — a real test would need that harness
  extension, left for later rather than silently skipped.

## Bugs found by live testing, fixed on `fix/run-status-and-project-dedup` (2026-10-29)

Three issues reported from live testing (screenshots, not code), fixed on a separate branch from the phase/retrofit
work above to avoid touching shared files mid-edit. Not phase work; tracked here as bug/fix entries instead.

**Bug 1 — a failing verify/lint step was shown as a green "done" pass (fixed).** A completed run's "Run the tests"
step showed a green checkmark, while its own summary read "tests failing: ... ; 1 lint step(s) failed." The run
still reached "Approve result" looking like a routine pass, and a human approved it without a strong signal that
anything was wrong. Root cause: `agent/playbooks/steps.py::finish()` hardcoded every step's recorded status to
`"done"` regardless of outcome — the pass/fail text was in the prose summary, but the status field itself (which
drives the Timeline, the Plan checklist, and ultimately whether `run.status` can be trusted) never said otherwise.
The human-approval gate mechanism itself was confirmed working correctly (real Postgres `approvals` rows, real
timestamps) — this was purely a misleading-status bug, not a bypassed gate.

Fix: `finish()` now takes `ok: bool = True`; `ok=False` records `"failed"` on both the step and its plan item
(`PlanStatus`/`StepResult` already modeled `"failed"`; plan items didn't). Threaded `ok=` through every playbook's
verify/test/lint/build/migration-trial outcome step: `new_app` (the exact reported case — tests green **and**
lint failing both now gate), `bug_fix`, `write_code`, `code_review` (lint findings alone aren't a failure — a
linter that couldn't run is), `performance`, `refactor`, `security`, `translate`, `upgrade`, `devops`, `docs`
(wording findings aren't a failure — a build that ran and failed is), `architecture_change` (`design.py`'s verify
and restructure steps, `microservices.py`'s foundation step), `db_change` (apply and verify), `feature` (build and
verify), and the `tests` playbook's write_verify step. Left as default (`ok=True`, no change) the genuine baseline
steps that check the state *before* a change as context, not as this step's own pass/fail (`db_change.study_node`,
`feature.survey_node`, `refactor.map_node`, `upgrade.survey_node`, `architecture_change/design.py`'s baseline step)
and steps whose job is to report/publish rather than verify.

Frontend: the Timeline and Plan checklist render a distinct failed icon/label instead of a step with status
`"failed"` getting swept into green by the old `run.status === "completed"` fallback; the run-level status badge
shows `"<status> · a step failed"` instead of a clean `"Completed"`; the `GateCard` approval screen (where a human
actually clicks Approve/Edit/Reject) shows an unmissable red banner when any step failed, instead of a routine-
looking card with the warning only in a scrollable markdown box.

Tests: `agent/tests/playbooks/test_steps.py` (new) unit-tests `finish()`'s `ok` parameter directly.
`test_new_app.py`'s existing `test_a_failing_app_is_shown_red_not_hidden` only ever asserted `state["passed"]` —
never the step's own recorded status — which is exactly how this shipped unnoticed; it now also asserts
`state["steps"]["verify"]["status"] == "failed"`, plus a new case for tests-green-but-lint-failing (the literal
reported scenario). `test_security_playbook.py` gained a green-path and a red-path case for its `verify` step.
Frontend: `run-view.test.tsx` (new) and `pending-card.test.tsx` cover the Timeline/badge/GateCard rendering.
Commits: `cc45b0d` (core fix + the 4 most directly implicated playbooks), one follow-up (mechanical `ok=` threading
through the rest).

**UX problem — the run page led with the full agent timeline instead of pass/fail + code + a run action (fixed).**
Redesigned so a settled run leads with a new `ResultCard` (honest Passed/Failed/Cancelled, the failing steps' own
summaries, a tabbed code/diff viewer over the run's artifacts, and the `DeliverPanel` as the run/deploy action);
the full agent-by-agent Timeline moves into a collapsible "Agent activity" section (open while a run is still
active, collapsed once settled). The chat's inline Done card had the same "shown as done when it isn't" pattern
as Bug 1 — it always drew a green checkmark regardless of outcome; `_done_card()` now computes `passed` from the
run's own plan items and sends it as `data.passed`, and `DoneCard` draws a destructive X instead when it's false.
Tests: `run-view.test.tsx` (extended) and `cards.test.tsx` (new). Commit: `f2f569f`.

**Bug 2 — sidebar accumulates near-duplicate projects/chats (root-caused, partially fixed).** Research (a
background agent) found two distinct causes, not one:
1. `new_app` minted a brand-new `Project` row on **every** run, including a plain retry in the same chat — there
   was no concept of "the project this chat is already building." `apps/api/src/codewright_api/chat.py::_start_work`
   hardcoded `project_id=None` for every `new_app` request regardless of what the conversation had already built.
   **Fixed:** `RunManager.create_project` (`apps/api/src/codewright_api/runs.py`) now settles the run's
   conversation onto the project it just created, the first time only (`conv.project_id` stays whatever it was if
   already set); `_start_work` passes the conversation's own `project_id` through unconditionally instead of
   forcing `None`, so a second new_app request in the same chat reuses the project the first one created (the
   `new_app` graph's `scaffold_node` already skips re-scaffolding when a project exists — this is the same "a
   rework keeps the project the first pass created" path a gate rework already uses, now also reached across runs,
   not only within one run). A genuinely different app still gets a clean project by starting a new chat, the same
   way every other intent (`add_feature`, etc.) already works. Test: `test_runs.py::
   test_create_project_settles_the_conversation_once_so_a_later_run_reuses_it`.
2. "Internal test/eval runs leaking into the visible Projects list" — checked every eval script
   (`evals/write_code.py`, `verify.py`, `run_tasks.py`, `review.py`): none of them create a project (`write_code`
   is project-less; `explain`/`review` take an existing `--project`, never `project_name`). There is currently no
   automated code path that creates "internal" projects, so there is nothing to flag — the actual clutter (the
   "phase13-tictactoe"/"phase13-calc-check" entries, the many "Codewright Tic-Tac-Toe" / "Add price alerts..."
   entries) reads as a developer's own manual live-testing via the real chat/API during Phase 13 work, which is
   indistinguishable at the code level from genuine user activity — both do the exact same thing through the same
   endpoints. Building a speculative "internal" flag/migration for a problem no current code path causes isn't
   worth the schema churn. **Not fixed, by design**; `DELETE /projects/{id}` and `DELETE /conversations/{id}`
   already exist for manual cleanup of the stale entries already in the live DB — left for you to pick which ones
   to keep rather than guessed and deleted.
Branch: `fix/run-status-and-project-dedup`.

## Phase 8 eval (ADR 0023), run 2026-10-29

`python3 evals/write_code.py` fails immediately (`ModuleNotFoundError: No module named 'evals'` — it must run as
`python3 -m evals.write_code`, not as a script path; the script's own docstring example is wrong, worth a 1-line fix
later). Re-run correctly: see the Phase 8 section below for the result once it finishes.

## How to run

```bash
cp .env.example .env     # first time only: set POSTGRES_PASSWORD (openssl rand -hex 16) and LLM_REMOTE_GPU_URL
docker compose up -d --build --wait
# Chat app:   http://localhost:3000        Runs: http://localhost:3000/runs
# API docs:   http://localhost:8000/api/docs
# Readiness:  http://localhost:8000/api/health/ready
make check               # every lint/type/test check, inside Docker
```

Optional compose profiles: `host-llm-bridge` (reach a llama-server bound to the host's 127.0.0.1; on in `.env`),
`llamacpp-cpu`, `ollama-cpu`, `langfuse`, `checks` (used by `make check`).

## Retrofit: real-sandbox playbook tests (started 2026-10-29)

Policy change: every playbook's automated tests so far (`agent/tests/playbooks/*.py`) use a fully mocked sandbox
(`FakeProject`/`FakeServices`) — they prove the graph/gate control-flow but execute **zero** real language
toolchain. Per the user's plan, retrofitting this phase by phase, highest-risk first (Phases 8-11, 17, then 7 and
18, then 12/14, then 4/6/13/15/16), with one shared harness instead of bespoke fixtures per phase.

Built so far (infrastructure, not yet wired into a specific phase's tests):
- `agent/tests/sandbox_harness.py`: `RealProject`, a `ProjectTools` implementation backed by the real sandbox
  runner (no mocks) — `test`/`lint`/`sandbox`/`run_step` actually run `pytest`/`go test`/`ctest`/`vitest` in the
  sandbox; `search` is a real (if simple) keyword grep over the checkout; `verify`/`db_trial` are honestly
  "not available in this harness" rather than faked. The `workspace` fixture (a throwaway real sandbox session)
  moved to `agent/tests/conftest.py` so every test module gets it from normal pytest fixture discovery.
- `agent/tests/cassette.py`: `cassette_llm(name)` replays `agent/tests/cassettes/<name>.json` (recorded LLM calls,
  in order) through the same `LLMClient` interface `llm_returning` uses, so a test can swap one for the other.
  `CASSETTE_RECORD=1` (with `LLM_REMOTE_GPU_URL` set) records a fresh cassette against the real configured model
  instead — `make check`/`make check-sandbox` only ever replay; a missing cassette fails loudly.
- `agent/tests/fixtures/mini_apps/{python,typescript,javascript,go,cpp}/`: one shared tiny app per language
  (`greet`, `word_count`, and a deliberately buggy untested `avg` — off-by-one, the same bug shape the existing
  fake tests already use), reused across phases instead of new fixtures per phase. `agent/tests/test_mini_apps.py`
  (`make check-sandbox`) proves all 5 actually build and pass their tests in the real sandbox — this is the
  baseline every retrofit test builds on. Finding during this: TypeScript/JavaScript `npm install` without a
  pinned exact version and without `optionalDependencies: {vite}` hits a real `npm`/arborist bug
  (`Cannot read properties of null (reading 'edgesOut')`) with `vitest@5.0.3`'s peer dependency graph; matching
  the `library-ts` template's caret-range + optional-vite shape avoids it. Also needed `rootDir: "src"` in
  `tsconfig.json` (TypeScript 6's stricter common-source-directory check).

Open: no phase has a real-sandbox + real-cassette playbook test wired up yet (Phase 8 was next); `make check`
stays on the fast `FakeProject` tests, the new real-sandbox ones will live under `make check-sandbox`.

## Phase 19: Deepen the Language Packs (complete for this pass, 2026-10-29 — more framework coverage can land later)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 19.

| Task | Result |
|---|---|
| C++ package managers (vcpkg/Conan) | `agent/language_packs/cpp.py`: `detect()` records `package_manager` (`vcpkg`/`conan`/`none`) from `vcpkg.json`/`conanfile.txt`/`conanfile.py`. Conan: a real `install` step (`conan profile detect --force \|\| true; conan install . --build=missing`) runs before `configure`, which points `CMAKE_TOOLCHAIN_FILE` at the generated toolchain; wired into build/test/lint/coverage. vcpkg: manifest mode — `configure` alone gets the toolchain flag (assumes `/opt/vcpkg`, manifest mode auto-installs during configure); both get `network: registry` only on the steps that actually need it, the test/ctest step itself stays offline either way. Conan is installed in `sandbox/images/cpp.Dockerfile` (pip, lightweight); vcpkg is **not** (needs a git clone + bootstrap, still deferred for disk headroom — the box is at 96% disk use; the pack code already assumes `/opt/vcpkg`, so adding it later is a Dockerfile-only change). Egress allowlist (`config/sandbox.yaml`) updated for both, plus `release-assets.githubusercontent.com` (Conan's build-from-source path hits this CDN host). Fixtures `cpp_cmake_vcpkg` (vcpkg + `fmt`) and `cpp_cmake_conan` (Conan + `nlohmann_json`, switched off `fmt` — Conan Center's `fmt` recipe hits a known self-named-component bug under legacy CMakeDeps, unrelated to our pack code) plus `test_cpp_package_managers` lock in the planning logic. **Real-sandbox-verified**: `test_cpp_conan_fixture_builds` actually runs `conan install` + `cmake configure` + `cmake --build` in the sandbox and passes. |
| **Infra bug found and fixed while verifying Conan**: the sandbox runner starts a fresh container per job step, keeping only `/work` and configured per-toolchain cache mounts across steps (`sandbox/runner/src/codewright_sandbox/runner.py`'s `_mounts`/`caches`). The `cpp` toolchain had no cache mapping (`cpp: {}` in `config/sandbox.yaml`), so Conan's package cache (`$HOME/.conan2`, written during the `install` step) vanished before the `configure` step could read it — CMake failed with "Imported target ... includes non-existent path". Fixed by mapping `/home/sandbox/.conan2` into the same persistent cache volume Go/Node/Python already use (`cpp: { /home/sandbox/.conan2: cpp/conan2 }`). This would have broken every real Conan build, not just this fixture. |
| Django REST Framework | `agent/language_packs/python.py`: `ModelViewSet`/`ReadOnlyModelViewSet` registered on a DRF router now produce real routes (the 6 standard CRUD routes, trimmed to list/retrieve for read-only) plus any `@action`-decorated custom endpoint, each linked `handled_by` to `ViewSet.method`; `Serializer`/`ModelSerializer` subclasses become `serializer` graph nodes. New fixture `python_django_drf` (a `Product` model, `ProductSerializer`, a `ProductViewSet` with one custom `@action`) — the first fixture/golden-test coverage Django has had at all; `test_django_rest_framework` checks the generated routes and nodes. Plain Django (`path()`, `models.Model`) already had basic support from an earlier phase; this only adds DRF's router-based routing on top. |
| NestJS, Echo | Already had basic detection/routing from earlier phases (controllers+decorators for NestJS, `e.GET(...)`/`e.Group(...)` for Echo via the shared Go/Node route regexes) — confirmed with new fixtures this session: `go_echo` (Echo routes/groups) and `ts_nestjs` (`@Controller`/`@Get`/`@Post`), both asserted in `test_framework_meaning`. No pack code changes needed — the existing regexes already matched Echo's/Nest's syntax. |
| Verification | Full `make check` (ruff/mypy/pytest, 524 passed, 17 skipped) and `make check-sandbox` (`SANDBOX_TESTS=1`, 17 passed incl. every template, the C++ terminal fixture, the new Conan build, and the Python→C++ translate sandbox test) both green against the recreated stack (see the infra incident above). `make check-web` green too. |
| vcpkg (retrofit worktree) | Checked again: disk was 16GB free at the start of this session, 17GB after `docker image prune -f`/`docker builder prune -f` — not comfortably above the 15GB floor this session was told to stop at, especially sharing the Docker daemon with concurrent work in another worktree. Skipped again, per the session's own instructions for this exact case; `agent/language_packs/cpp.py`'s `/opt/vcpkg` assumption is untouched, so it's still just a Dockerfile change once there's real headroom. |
| Go: `staticcheck` lint (retrofit worktree) | CODEWRIGHT.md 8.3's own table names "go vet, staticcheck" — only `vet` was wired. Added `staticcheck@v0.8.2` to `sandbox/images/go.Dockerfile` (`go install`, pinned); `agent/language_packs/go.py::lint_steps` now runs `vet` → `staticcheck` (optional, like C++'s `clang-tidy`) → `gofmt`. Sanity-checked for real with `docker run` against the rebuilt image on the `go_gin`/`go_echo` fixtures (both clean). `test_go_staticcheck_lint_step` (fast) locks in the plan; golden snapshots `go_gin.json`/`go_echo.json` regenerated to match. |
| C++: Conan package-manager *upgrade* path (retrofit worktree) | The Open item below, built: `agent/language_packs/cpp.py` adds `_requirements()` (parses conanfile.txt's `[requires]` pins) and `CONAN_BUMP_SCRIPT` (rewrites one `pkg/version` pin in conanfile.txt/.py — conanfile.py's own free-form `requires =` isn't parsed, only the literal `pkg/version` text is rewritten if present). `outdated_steps` now runs a real `conan search <pkg> -r=conancenter` per pinned dependency and reports `pkg pinned -> latest` when they differ (registry network, Conan only — vcpkg still has no scriptable registry query, vendored/FetchContent has no registry at all). `upgrade_steps` returns just the bump step (same contract as every other pack: the caller re-verifies with `build_steps()`/`test_steps()` afterwards, it doesn't re-verify itself). Not wired into `/upgrade`'s chat flow (`agent/playbooks/upgrade/` is out of scope for this worktree, owned by concurrent work elsewhere) — this is the Pack-level capability that playbook would call. `test_cpp_conan_upgrade_path` (fast) and `test_cpp_conan_bump_script_rewrites_the_pin` (fast) lock in the planning/rewrite logic; `test_cpp_conan_upgrade_bumps_and_rebuilds` (`pytest.mark.sandbox`, written but not executed live this session — see below) bumps the existing `cpp_cmake_conan` fixture's `nlohmann_json` pin from 3.11.3 to the real 3.12.0 Conan Center release (confirmed present via a direct `docker run conan search` against the rebuilt sandbox image) and rebuilds. |
| Verification (retrofit worktree) | `make check`-equivalent run clean under an isolated compose project (`-p cw-p19-lp`, per this worktree's own instructions, to avoid colliding with concurrent work on the shared Docker daemon): ruff, ruff format --check, mypy and the full pytest suite (518 passed, 53 skipped — all sandbox-gated) all green. The new `pytest.mark.sandbox` C++ upgrade test was lint/type-checked but **not executed live**: `sandbox-runner`'s `WORKSPACES_VOLUME`/`CACHE_VOLUME` env vars in `deploy/docker-compose.yml` are hardcoded to the default `codewright_`-prefixed volume names regardless of `-p`, so a real `make check-sandbox` run from an isolated compose project would reach into the same cache/workspace volumes the live stack and other worktree may be using concurrently — judged not worth that risk for one test. The underlying mechanics it exercises (the real `conan search` output, the real cmake/conan build of this exact fixture) were each verified directly instead (see the Go/C++ rows above and `test_cpp_conan_fixture_builds`, already real-sandbox-verified from the earlier pass of this phase). |

Open: vcpkg still not installed/buildable (deferred for disk headroom — still true this session too, see the
disk-cleanup list below); the C++ upgrade path isn't wired into the `/upgrade` chat flow itself (pack-level only);
`test_cpp_conan_upgrade_bumps_and_rebuilds` hasn't been run against the real sandbox yet (see Verification row above); more
framework coverage from the spec's examples (more templates, deeper linters for Python/TypeScript/C++) is still
ahead — this is a 3-week phase and each session so far has covered one or two concrete slices of it.

## Phase 18: Translate (ADR 0033; built, verified against the real sandbox, not yet run on a real project)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 18.

| Task | Result |
|---|---|
| `translate_language` playbook | `agent/playbooks/translate/graph.py`: survey (Code Analyst: finds the component, enumerates units with `inventory.py`, captures black-box cases with `blackbox.py`) → plan (Solution Architect: target language + skeleton from `target.py`, declines same-language) → **approve plan** → translate (Backend Developer: one unit at a time, callees first, assembled into one file, built with the Reflection loop, max 5 tries) → verify (QA Engineer: CLI checked against the same black-box cases; HTTP services fall back to the Pack's own tests, honestly marked "not implemented yet") → review → **approve result** → publish (new commit under `translated/<package>-<pack>/`, next to the original; nothing cut over). `cli`/`api` only; library/app/web declined with reasons. |
| Wiring | Registered in `agent/playbooks/registry.py`; the chat intent/tier/intake wiring for `translate_language` already existed from an earlier phase. |
| Tests | 6 fake-sandbox tests (3 decline paths + a full happy-path run, a tiny `calc.py` → C++) and 1 real-sandbox test (`pytest.mark.sandbox`): the same fixture actually executed in Python to capture cases, actually built with CMake/Ninja in the sandbox, the compiled binary actually checked against those cases. All pass. `make check`-equivalent (ruff, mypy, 132 playbook tests) clean. |

Open: the GoShop-service-rebuilt-in-Python acceptance item (needs a real project and a live run); HTTP-service translation has no real-sandbox test, only the fake-sandbox path.

## Phase 17: Architecture change III, data/other targets, finish (ADR 0032; built, unit/fake-sandbox tested, not yet run live)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 17.

| Task | Result |
|---|---|
| Microservices finish | The database-split check/contract stages, `apply.sh`/`rollback.sh`/`STAGES.md`, and (when the design has sagas) the saga library + its generated tests (`agent/microservices/data.py`) are now actually written during conversion, not just available as unused functions; the frontend step also rewrites API-address literals to the gateway and writes `GATEWAY_ROUTES.md`. Two real bugs found by executing the generated output (not just asserting on its text): a saga crashing before its first step had nothing to resume from, and the API-address regex matching "localhost" as an API line via the substring "host". |
| `merge` target | Real: detects extracted services from the working tree itself (the shim mark + the service name), restores the local code, deletes the service folder/runbook, drops the gateway route, regenerates `nginx.conf`, removes the dead anti-corruption layer. Refuses a service already finalized at 100% cutover (nothing to restore). |
| `serverless` target | Real, Python only: reuses `extract.py`'s entry-point analysis to find stateless groups (no table, no saga), packages each as `services/<name>/` with a handler per entry point and a deploy-manifest template. The monolith's own copy is untouched; wiring a real trigger and deploying are left as a runbook, matching ADR 0031's own canary pattern. |
| `event_driven` target | Real for the provably safe half only: an in-process pub/sub bus plus subscriber registration, added after the existing function (can't change its direct-call behavior). Rewriting the producer's call site to `publish()` is deliberately not done mechanically (AST can't prove a return value is unused) — instead a generated, human-reviewable `EVENT_REWRITE_REVIEW.md` names every call site. |
| Reports | `generic_comparison()` extends `COMPARISON.md`/before-after graphs to merge/serverless/event_driven, reusing the existing Deliver machinery unchanged. |
| Tests | 56 new/changed tests, including a full-graph acceptance test (`test_architecture_merge.py`) that drives the real graph with a fake sandbox/replay and merges a small multi-service fixture back into one app with **0 regressions** — the spec's exact acceptance wording. 401 passed, 15 skipped (sandbox tests), 1 pre-existing unrelated failure (`test_checkpoint_postgres.py`, a stale-container-password issue). ruff/mypy clean. |

Open: the GoShop saga-paths-replay-0-regressions acceptance and the M4 demo (need a live run); `serverless` never wires a real caller or deploys; `event_driven` never rewrites a call site, only documents where one would go; the database-split stages/saga library/gateway rewrite are only exercised against a fake `project.db_trial`, never a real PostgreSQL sandbox.

## Phase 16: Architecture change II, microservices build (ADR 0031; built, live-verified on notes-api-python)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 16.

| Task | Result |
|---|---|
| Foundation | `agent/microservices/foundation.py`: gateway (nginx), broker, JWT auth and event libraries, Compose and CI, generated for the chosen design. A failed foundation skips to the report. |
| Per-service loop | spec → scaffold from the template library → extract (Python) → ACL shim (0/50/100% and loopback) → tests → replay → undo on red (tests or replay regression) → commit → cut-over (`finalize` removes the local code, flips the gateway route). Specs are written in parallel (`max_parallel`); monolith changes are sequential. |
| Database split | Schema ownership per service, outbox/saga notes; trial on a real PostgreSQL when a database sandbox exists, else reported "not tried". |
| UI | A service board card in the run view. |
| Tests | Real generated code is executed in tests (JWT/event libraries, ACL shims, an HTTP round trip to an extracted service); two whole-run tests (Python project, Go design) with a fake sandbox and replay. 170 pass in the playbook, microservices and decomposition folders. |

Not demonstrated: no image built or started (sandbox has no Docker daemon); the canary (shadow → 10% → 50% → 100%) is config and a runbook, not a run; shadow mode and replay against a running service; only Python is extracted (Go/TS/C++ services are scaffolded and their code stays in the monolith); the gateway doesn't verify the JWT; the frontend step only points the frontend at the gateway; arguments and results must be JSON-serializable. The web service board and the generated FastAPI router were not type-checked or run.

**Live-run session, 2026-10-29 (`notes-api-python`; GoShop can't exercise this since it's Go, and extracting Go is
out of scope by your call):** three real bugs found and fixed by actually driving this live, repeatedly, to green:

1. **A stale baseline falsely undid the foundation.** The project's newest recording (made the day before) had 503
   on every exchange (the recorder had raced the app's startup), and `baseline_recording()`
   (`agent/playbooks/change_core.py`) reused it unconditionally; replaying today's normal 200/401 answers against
   yesterday's all-503 baseline was flagged as 16 regressions and undid a good foundation commit. Fixed (`ef77fa0`):
   a recording where `server_errors + unanswered` covers every exchange is skipped for an older usable one, or a
   fresh recording.
2. **A parallel step crashed on a second, simultaneous interrupt.** With two services building at once
   (`max_parallel`), one hit "model server unavailable" while another reached `gate5` in the same tick. Resuming
   with a bare `Command(resume=answer)` applied that one answer to *every* pending interrupt — the retry string
   reached `gates.py` expecting a decision dict and crashed (`AttributeError: 'str' object has no attribute
   'get'`). Fixed (`ca2d37e`): each pending prompt now carries its own interrupt id, and `answer()` resumes with
   `Command(resume={id: answer})`, targeted. Confirmed live afterwards: two `gate5` prompts fired in the same
   superstep (`eventing`, `root-configuration`) and both answered cleanly with no crash.
3. **A scaffolded service's own tests broke the monolith's test run.** Once `foundation` succeeded, every one of
   3 per-service build attempts came back "undone: ... collection failure" — not a real regression: `detect()`
   folds a nested Python manifest into its outer root component, so the just-scaffolded `services/<name>/` was
   never tested as its own component, yet the root's own `pytest` still recursed into it by default and failed to
   collect a package that was never installed into the root's venv. Fixed (`6496c22`,
   `agent/language_packs/python.py`): a component's own test run now `--ignore`s any nested directory with its own
   Python manifest.

All three are confirmed fixed by unit tests, and then by a full clean end-to-end live run once the GPU's ngrok
tunnel (down for a while mid-session, unrelated to Codewright) came back: `foundation` → **13 file(s) written**,
not undone; 5 service groups planned; **`application`, `authentication` and `events` extracted for real** (tests
green, 0 replay regressions each); `database` and `root` correctly came back "scaffolded, not extracted:
translating to another language is Phase 18" (their groups are Go/other, which this phase doesn't extract — the
spec's own acceptance criterion names GoShop here, which is Go end to end and genuinely can't be satisfied this
way; by your call, Go extraction itself is out of scope, and this run demonstrates the Python path is now real and
clean). `db_split`, `frontend`, `report` and `deliver` all completed; delivered on branch
`codewright/architecture-20261029-103058`. Two simultaneous `gate5` interrupts (two services reaching it in the
same tick) answered cleanly with no crash, directly exercising fix #2 above.

## Phase 15: Architecture change I (ADR 0029; built, not yet run on a real benchmark)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 15.

| Task | Result |
|---|---|
| Recommend + To-Be | `target=recommend` picks the simplest target that fits and says why microservices are or aren't justified; a To-Be design for any target with "why this shape", alternatives, events and sagas; typed edits ("move payment to order") re-validate against the rules. |
| Decomposition engine | Louvain grouping of the module graph, merged by rules (one frontend, one owner per table, no sync cycles, chatty pairs merged, no tiny services); scored, alternatives kept. Language Advisor keeps the language unless another clearly wins. |
| Clean modules / modular monolith | Rules + stdlib checker written into the project (`architecture/boundaries.json`, `check_boundaries.py`), existing violations are known debt. Mechanical moves (Python moves + expose; TS/JS moves), one commit each, tests after each, a red move restored exactly, replay at the end. Go/C++ get design and rules, no moves. |
| Behavior | `simulate=True` keeps the old stub steps; microservices conversion is still simulated (Phases 16-17); serverless/event-driven/merge conversion refused up front (designable); a real run needs a project. |

Open (acceptance not demonstrated): a Python benchmark restructured with 0 replay regressions (tested on a small temp repo with a fake replay); GoShop → ~5-service design (fixture gave 4 backend groups + frontend because a shared `db` module joined `product`; real import not run). `test_runs.py`/`test_db.py` edits need Postgres and have not run.

## Phase 13: New app (ADR 0030; `new_app` built, not yet run live)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 13.

| Task | Result |
|---|---|
| `new_app` playbook | requirements → [gate] → design → [gate] → [screens → gate] → scaffold → build → verify → review → docs → **approve app** → publish. Small = 1 gate, medium = 2 (plan, app), large = 4 (requirements, design, screens, app). |
| Stack rules | `new_app/stacks.py`: app type → options with one recommended and a reason; the user's language wins; only the 5 languages; unsupported language declined with the closest stack; a missing template falls back and says so. |
| Own project | The app is built in a new project (`create_project`), so Preview/Tests/other playbooks work on it; result card shows red builds as red; GUIDE.md run section comes from the template manifest. |
| Chat | New app inputs and size (from the card's tier) wired in chat; a new app never attaches to the chat's current project; budgets for the playbook. |
| Template library | All 17 templates of CODEWRIGHT.md 8.4 exist (12 added): Next.js sites, 3 full-stack (FastAPI/Go/Node + Next.js + Postgres, auth, CRUD, admin, Compose, CI), cli-go, api-fastapi/node, 4 libraries. Run locally: Go/Python/TS tests, `next build`, the 3 backends against real PostgreSQL. Not run: Docker builds, C++ GoogleTest, sandbox tests, CI. Go templates say go 1.26 (tested at 1.23). |
| Tests | `agent/tests/playbooks/test_new_app.py` (stack rules, a whole small run, red build, gates per size). Targeted tests pass; the full `make check` is the end pass. |

| Where to keep it | The Done card of a new app asks: ZIP download, local folder, GitHub PR, **Google Drive as a folder** or **Drive as one ZIP** (the user picks; the folder is the usual choice). An opt-in box deletes the code from this machine after a successful Drive/GitHub upload (kept if any upload fails; the project stays listed as delivered with the link). |

Live run, 2026-10-29: a real in-use run (the user's own, not a benchmark) asked for "a terminal-based calculator"
and got scaffolded as a full-stack Next.js+FastAPI web app instead of a Python CLI. Root cause (fixed,
`agent/playbooks/new_app/stacks.py`): the `webapp` kind's rule words included the bare word "users", which the
requirements Q&A almost always contains (the model's own answer to "who is the main user?" is "General users"),
so it outranked the real "terminal" signal since `webapp` is checked before `cli`. Dropped that trigger word (kept
`multi-user`, which is a real signal); confirmed fixed by re-running the same request live: now correctly
scaffolds `cli-python` with the right file layout (`src/termicalc/{core,cli}.py`, `tests/test_core.py`).

Tic-tac-toe live run, 2026-10-29: web-react-ts, 4 files, correctly reached the approve_result gate **red** (3
failing tests in `isDraw`/`getGameState`/move validation) and showed the failures verbatim instead of hiding them —
the harness working as designed; the game-logic bugs themselves are the 9B model, same class as the Phase 8 eval.
Rejected (not kept).

Open: more live runs (calculator in the other 4 languages, 10 small + 5 medium apps, inventory, clinic); the M3
demo; Preview of a browser app / terminal app is started from the project's Preview tab, not by the playbook.

## Phases 12 and 14: Frontend and DevOps (ADR 0027, 0028; built, not yet run live)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 12 (Phase 14 shares the same playbook).

| Task | Result |
|---|---|
| `frontend_modernize` | survey (build, tests, baseline screenshots) → plan → **approve plan** → migrate → modernize → verify → **approve result** → publish. Each stage is its own commit and is undone exactly when the build or tests go red. |
| Next.js migration | React + Vite → Next.js App Router computed from the project's files (no model): the existing `App` runs as a client component under one catch-all route; env vars, dev proxy (as rewrites), tsconfig and the test setup are carried over. Parity: screenshots compared with the baseline. |
| Modern, accessible UI | Rule-based: a `:where()` design layer (tokens, dark mode, focus ring, reduced motion, responsive) and automatic fixes for alt text, page language, viewport, low contrast and removed focus outlines. Labels, icon-only buttons and clickable non-controls are reported, not guessed. No model redesigns layouts. |
| `devops_deploy` | survey → plan → **approve plan** → generate → verify → **approve result** → publish. Dockerfile + `.dockerignore` per deployable component, Compose (with the databases the dependencies mention), a CI workflow from the packs' own build/lint/test steps, Kubernetes only when asked. Templates per language pack; existing files never overwritten. |
| DevOps checks | Static: pinned images, non-root user, COPY sources exist, valid YAML, no secrets, no Docker socket. Then the CI's commands run in the sandbox. **Images are not built** (the sandbox has no Docker daemon, by design); the card says so. |
| Fix | Phase 11 asked verification for a `screenshot` action that does not exist; it is `screens`. |

Open: live runs on a real React + Vite app and on GoShop; the "page by page" split of the catch-all route and the model-written redesign are not built.

## Phase 11: Add a feature (ADR 0026)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 11.

| Task | Result |
|---|---|
| `add_feature` | survey → stories → design → **approve plan** → build → verify → review → **approve result** → publish. Committed only when the tests pass and a new migration applies and rolls back on PostgreSQL; otherwise nothing is kept. |
| Feature by analogy | The model picks the existing feature the new one is like and names it; the plan follows that feature's real files (adapted copies, wiring, appended type declarations, a migration). Left-out files are listed with reasons. |
| Build order | Types, model, migration, repository, service, handlers, tests, then wiring; each file sees the earlier files' declarations; up to 5 fix rounds under feature build rules. |
| Cancel | A cancelled run's unfinished changes are stashed and the project goes back to its branch (all playbooks). |
| Live (GoShop) | GoShop already has a wishlist, so "price alerts" (like the wishlist) was the test. One run went green: 12 files, 350 tests, replay 0 regressions/25, screenshot. Review found its migration lacked the `target_price` column, which led to the migration trial gate; it was not approved. Later runs vary with the 9B model (type mismatches between layers). |
| Live session, 2026-10-29 | 3 more attempts, same request, each a distinct build-time type error, all auto-removed (never committed, nothing left in the project): `targetPrice` string→float64 conversion in the repository layer; a TypeScript frontend file importing a `PriceAlert` type never exported from `@/types`; `req.TargetPrice` referenced on a request struct whose field was named differently. No two attempts failed the same way. This is the same 9B cross-file-type-consistency limitation already on record, not a playbook bug — confirmed again rather than fixed. |

Acceptance still open: a price-alerts run that passes the migration gate and is approved (re-run once the model is stable); acceptance-criteria tests are thin where the analog's tests need generated mocks. 3 more live attempts this session (above) still didn't land one; not retrying further for now given the time already spent.

## Phase 10: Security, upgrade and database change (ADR 0025, Milestone M2)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 10.

| Task | Result |
|---|---|
| `security_review` | scan (secrets, security lint, dependency audit) → model review → grounded findings; "fix" requests are tier 2 (plan, fix, tests, replay, rescan). Live on GoShop: seeded AWS key found and removed, 349 tests green, replay 0 regressions/25. |
| `upgrade` | outdated direct dependencies → plan → one package at a time (bump, build, test, adapt code if red, exact revert if still red), one commit each. Live on GoShop: grpc and x/crypto bumped, 349 tests, replay 0/25. Release notes are not read, and the brief says so. |
| `database_change` | next numbered migration + rollback → tried on a fresh PostgreSQL sandbox database (up, down, row counts, checksums, schema, query plans). Live on GoShop: index on `products.category_id`, rollback exact, Seq Scan to Index Scan. |
| Model connection | LLM client retries a dropped connection (3 times). |

Known limits: model false positives in the security review (seen once, shown at the gate); PostgreSQL only; no engine changes; C++ has no dependency audit.

## Phase 9: Refactor and performance (ADR 0024)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 9.

| Task | Result |
|---|---|
| `refactor` | map → plan → **approve plan** → refactor (Reflection loop, undo on failure) → verify (tests + replay) → review → **approve result** → publish. Live on GoShop `pkg/utils`: 4 files refactored, 349 tests green, replay 0 regressions/25 requests, a real Tech Lead finding, committed on `codewright/refactor-*`. |
| `improve_performance` | baseline (k6) → find (search + static scan for N+1/sleeps/rescans) → **approve plan** → optimize → verify (tests + replay + benchmark) → review → **approve result** → publish. Live on a seeded `time.Sleep` in GoShop's `ListCategories`: found and removed from the code alone, tests green, replay 0 regressions, correctly reported **not measured** instead of a fake number. |
| Finding | GoShop's own per-IP rate limiter throttles k6's benchmark traffic (same source IP) to near-0% success regardless of endpoint. Fixed by having the benchmark recognize a high failure rate as "a guard is rejecting this load" and refuse to report it as latency, rather than bypassing the limiter. |
| `change_core.py` | Shared by both: whole-file rewrites, Reflection loop, undo-on-failure, replay-backed "unchanged behavior". |

Acceptance still open: a repeat with the sandbox's `RATE_LIMIT_REQUESTS` raised, to get a real before/after number (not just "not measured" proven honest).

## Phase 8: Write code, fix and test (ADR 0023)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 8.

| Task | Result |
|---|---|
| `write_code` | A playbook now (no project needed): code + tests in a throwaway workspace, run in the real sandbox, Reflection loop (max 5; fixes the tests on attempts 3 and 5), explanation with complexity, one approval, optional commit into a project. Live: palindrome in Python ✅ (13 tests), reverse a linked list in Go ✅ (attempt 4), binary search in C++ ⚠️ failed after 5 attempts (code and tests disagreed on the API) and says so. |
| `fix_bug` | locate → reproduce → fix (Reflection) → Tech Lead review → one approval → branch `codewright/fix-*`. Live on GoShop with a seeded off-by-one in `pkg/paging`: right file, failing regression test, fixed in 1 attempt (1-line diff), 342+ tests green. |
| `write_tests` | targets → tests in Codewright's own file → before/after tests and coverage → one approval → branch `codewright/tests-*`. Live on GoShop `pkg/paging`: 342 → 352 passing, no regressions. Files that never pass are dropped and reported. |
| Reflection loop | `agent/playbooks/reflection.py`, feedback = failing cases + the broken step's key output lines. |
| UI | The Report tab shows diffs and written code; Done cards list the files on the branch. |

Acceptance still open: more seeded bugs.

### Eval record (2026-10-29): `python3 -m evals.write_code`, all 20 `EXAMPLES.md` §2 requests

**10/20 passed** (`evals/results/write_code-20261029-*.json`). By language: Go 2/2, Python 7/12, C++ 1/4, TypeScript
0/1, JavaScript 0/1.

Real failures (9B model, not playbook bugs): #1 reverse-linked-list (tail case wrong), #4 binary search with
duplicates (returns "not found" instead of an index), #8 balanced parentheses (wrong bracket-type matching), #11
Fibonacci memoization (still recurses past Python's limit on large n — memoized but not iterative/raised-limit),
#12 group anagrams (case-sensitivity test), #16 Dijkstra (C++ compile error, modifying a `const`-qualified pair
element), #18 debounce (cancel-after-leading-call fires twice), #20 matrix multiply (runtime abort). #10 (merge/quick
sort, C++) failed on a bug in the model's *own test*, not the solution: it called `assert()` (the one-argument C
macro) with 5 arguments, as if it took a message — a real distinct failure mode from #16, worth a note for whoever
builds C++ prompting further in Phase 19. #15 (Trie, TypeScript) failed on `node_modules/@vitest/utils/.../index.d.ts:
Cannot find name 'setImmediate'` — a Node types/lib mismatch in `write_code`'s TypeScript scratch scaffold, possibly
systemic rather than the model's fault; not chased further this session.

Two real bugs found and fixed getting to this honest number (both affected every multi-example eval run, not just
this one):
- **The eval script's own docstring example is wrong**: `python3 evals/write_code.py` fails immediately
  (`ModuleNotFoundError: No module named 'evals'` — it's a package, must run as `python3 -m evals.write_code`). Not
  fixed (1-line doc fix, left for the Phase 19/20 pass).
- **Sandbox session leak** (commit `d3b6f77`, `apps/api/src/codewright_api/runs.py`): `write_code`'s throwaway
  workspace gets a sandbox session keyed `scratch-<run_id>`, unique per run; nothing ever closed it, so every
  project-less run leaked one more session, permanently, until the 4th exhausted `max_sessions: 4` and every
  following example failed with "at most 4 sandbox sessions at a time" — not a code problem, a resource leak. The
  first full eval attempt returned 2/20 passed, entirely from this (18 false failures); fixed by closing the scratch
  session once `_drive()` reaches any terminal state (completed/failed/cancelled) for a run with no `project_id`.
  This had been silently inflating every multi-run eval all session; worth checking whether it affected earlier
  phases' own "N/N passed" eval numbers in this file too (not re-audited).

## Phase 7: Verification engine, done (ADR 0022)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 7.

| Task | Result |
|---|---|
| 1. Test runner + coverage | Every Language Pack reports coverage: `coverage` (Cobertura XML) for Python, `go test -coverprofile` for Go, Vitest/Jest cobertura for Node, `gcovr` for C++/CMake; `TestReport.coverage` (tool, covered/total lines, per-file) in the Tests tab. |
| 2. Characterization (QA sub-agent) | `agent/verification/characterize.py`: groups routes by resource (login first, shared prefixes stripped), orders groups by what their write handlers depend on, sends each group's route code + handler source to the model, retries once on 400/401/422 with the rejection as a hint, keeps the attempt with the most accepted steps. Falls back to a smoke journey (every GET without parameters) when no model is configured. |
| 3. Recorder, replay, diff, noise | `agent/verification/{traffic,noise,diff,replay,journeys,recorder}.py`. A recording is journeys sent from a reset app, a live browse through mitmproxy (`record-live`), or an imported HAR. Replay resets the app again, resends every request (one cookie jar per journey), and the `Linker` carries IDs/tokens/`Location` segments the app handed out from the recorded run to the new one. `Comparer` diffs status, a fixed set of headers and the JSON/text/binary body; each difference is **regression**, **noise** (a built-in or project rule explains it) or **intended** (an `Intent` the user gave). 0 regressions required to accept. |
| 4. Benchmarks + screenshots | `bench` replays a recording to get fresh IDs/tokens, then runs k6 (sharing the app's network) on its successful GETs, 5 virtual users for 20 s, compared with the last benchmark of the same recording. `screens` runs Playwright (new `browser` sandbox image, not yet built — see below) over the Language Packs' page routes, compared pixel-by-pixel with an accepted baseline (`accept` replaces it). |
| 5. Eval harness skeleton | `evals/tasks/registry.json` (playbook → case file → eval script) and `evals/run_tasks.py`, which runs each task and writes a combined pass/fail summary. Added `evals/verify.py` (imports a fixture, records+self-replays, asserts 0 regressions) with cases for `notes-api-python` (checked in) and `goshop` (third-party; takes `--project` instead of a repo). |

New sandbox images: `tools` (k6 0.57.0 + mitmproxy 11.1.3, built) and `browser` (Playwright + Pillow, **not built**: ~2 GB and disk was at 95%/11 GB free; `make sandbox-images` builds it along with the rest). `VerificationService` (`apps/api/.../verification.py`) runs everything from a sandbox session reset (fresh sidecars, migrations re-applied) so a recording and a replay meet the same state; its actions (`test`, `characterize`, `record`, `record-live`, `replay`, `bench`, `screens`) are under `/projects/{id}/verification/*` (SSE events while running). Tests tab: action buttons, live log, coverage bar, replay differences table with a noise-rules explanation and an "only changed" filter, benchmark table with before/after deltas, screenshot grid with diff overlays and an "accept as baseline" button, a live-recorder banner with a Stop button, and a HAR-import file picker.

### Acceptance results (2026-10-28)

| Check | Result |
|---|---|
| GoShop recorded and replayed with 0 regressions | ✅ Earlier in this phase, before the last round of changes: `record` (25 exchanges) then self-replay gave **0 regressions** (22 noise differences explained, 19 exchanges identical). Not re-run after the readiness and `normalize()` fixes below — do that before relying on it again. |
| A second language/type (Section 15.0) | ⚠️ `evals/repos/notes-api-python` (FastAPI/SQLAlchemy/Postgres) characterized and recorded correctly earlier, but its first replay found 1 regression + 5 server errors from a readiness bug (the sandbox gateway's `503 Starting` was read as a real answer). Fixed (`GATEWAY_WAITING` check) but **not re-verified live** — the fix needs a real run to confirm 0 regressions, which this session didn't do (time was spent finishing the remaining features and tests instead). |
| Reports render in the Tests tab | ✅ `make check-web` (24 tests) covers the new sections; not opened in a browser against a live replay this session. |
| `make check` | ✅ `make check-api`: ruff, ruff format, mypy clean; pytest **276 passed**, 6 skipped (sandbox tests). `make check-web`: ESLint, tsc, Prettier, Vitest **24 passed**. 41 new unit tests for `agent/verification` (traffic, noise, diff, replay incl. the Linker, journeys, bench, recorder). |
| Images and stack | ✅ `sandbox-runner`/`sandbox-gateway`, `api` and `web` rebuilt; `docker compose up -d --wait` → every container healthy; the 10 new `/verification/*` routes confirmed present via `/api/openapi.json`. The `browser` sandbox image is not built yet (see above), so `screens` and the Playwright step of `record-live`'s self-check won't run until `make sandbox-images` builds it. |

Found on the way and fixed: `journeys.normalize()` ran the gin-style `:id → {id}` substitution before the Flask-style `<int:id>`, so `<int:id>` became `<int{id}>` instead of `{id}` (caught by a unit test, not a live run). The notes-api readiness bug above.

**Left for next time, by your "stop testing, finish the features" steer:** build the `browser` sandbox image and
re-run `record`/`replay` live on both GoShop and notes-api-python to actually confirm 0 regressions after today's
fixes, and try `bench`/`screens`/`record-live`/HAR-import against a running app at least once. The code for all of
it is in and passes its unit tests and `make check`; what's unverified is only the live, real-sandbox path.

## Phase 6: Explain, Audit, Docs, Review, Skills, done (ADR 0021)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 6.

| Task | Result |
|---|---|
| 1. `explain_code` | `/explain` (or a question) in a project chat. The Code Analyst gathers the code first: the definitions of the names asked about in all 5 languages (implementation before handlers, with its doc comment, cut where it ends), where they're used, a module's outline and the code behind its dependencies, graph facts; search hits only if nothing else fits. Answer streamed, then a diagram drawn from the steps (Diagram tab); modules highlighted in the Graph tab. "Not found" instead of a story when the project has no such code. |
| 2. `analyze_audit` | `/audit`: As-Is (C4, dependencies, database map, hotspots) computed from the code, **Confirm As-Is** gate, security, quality, recommendations, `audit.md` + `findings.json` in the Report tab. |
| 3. `write_docs` | `/docs`: README, API, architecture and runbook from the code's facts; every endpoint and file checked; approval; a `codewright/docs-<time>` branch. |
| 4. Corrections | "That's wrong, X also calls Y" after an explanation or on the audit gate → facts on known modules, Save / Discard card, the As-Is redrawn; saved as `USER_FACT` on the graph and in project memory. |
| 5. `review_code` | `/review-code [file, folder or module]`: linters + secret scan + Tech Lead and Security Engineer per chunk; every finding must quote its code (checked; wrong lines corrected, invented ones dropped), severity capped by category, findings by severity with a suggested fix, score and top 3 (Report tab). Fixes come in Phase 8. |
| 6. Skills | Registry with 23 built-in skills (the `/` menu), user and project skills; Skills screen (create by form or Markdown, edit, test-run, enable, auto-use toggle, import/export); `/create-skill` and "save this as a skill" from a chat; auto-use with "Using skill"; imports validated, secret-scanned and disabled until enabled. |

### Acceptance results (2026-10-28, live on the running stack)

| Check | Result |
|---|---|
| GoShop questions answered correctly (eval set) | ✅ **11/11** (`python3 evals/explain.py --project <id>`; facts checked against the source). Was 7/11 before the context rework: long functions were cut, constants weren't found, module questions got no code. |
| `/review-code` correct on seeded issues in two languages | ✅ Python **9/9** (all with the right severity), Go **7-8/9** depending on the run (`python3 evals/review.py evals/data/review/seeded-<lang>.json`). ⚠️ About one false alarm per run in the clean file (the model argues itself into a bug); a second-opinion check is Phase 7. |
| Custom skill created from a chat, exported, re-imported, auto-used | ✅ "save this as a skill" → draft card → Save → export ZIP → delete → import (arrives **disabled**) → enable → a new request shows "Using skill: Generate Release Notes". |
| Audit reviewed by you | ⏳ ready for your review. Live on GoShop (~5 min): the correction "payment also calls product" on the Confirm As-Is gate became a saved fact and the As-Is was redrawn with it; report with C4 diagrams (the project's name, not its id), PostgreSQL and Redis (not the ORM), hotspots without generated files, 19 security findings (test fixtures grouped per file, names like `"x-access"` no longer read as secrets, type casts rated as types issues), 53 quality findings, 3 risks, 3 recommendations. |
| `/docs` | ✅ Live on GoShop (~45 s): README, API reference (43 endpoints from the code), architecture and runbook; every endpoint and file mentioned checked (0 problems); the documented build ran in the sandbox; committed on a `codewright/docs-<time>` branch after approval. Commands are shown as people type them (no report flags or `.codewright/` paths). |
| `make check` | ✅ ruff, format, mypy clean; pytest **235 passed**, 6 skipped (sandbox tests: `make check-sandbox`); ESLint, tsc, Prettier clean, Vitest **24 passed**. The flaky settings test from Phase 5 passed in this run; its cause (an event written for a run the database doesn't show) isn't found yet. |
| M1 demo | ⏳ with you |

Found on the way: Explain's definition patterns could run across lines (`\s` matched newlines), so an interface
declaration swallowed the real function; importing a skill reset its auto-use; a drafted skill could pick a
code-changing playbook and start an intake instead of answering; ESLint errors were reported as style nits. The
architecture-change stub still defaults its services to GoShop's names; it is replaced when that playbook is built.

## Phase 5: Language Packs + sandbox, done (ADR 0020)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 5.

| Task | Result |
|---|---|
| 1. `LanguagePack` + unsupported check | `agent/language_packs/`: one pack per language, several components per project (GoShop: Go API + TypeScript web). Projects mostly in another language get a notice on the project home with the closest supported languages; the chat declines them by rule. |
| 2. The 5 packs | Python, Go, TypeScript, JavaScript, C++ (CMake): detect, frameworks, entrypoints, install/build/test/lint/run steps, test reports in one shape (go test JSON, JUnit). Sidecars and migrations read from the project's own compose file. |
| 3. Sandbox runner | `sandbox-runner` (the only service with the Docker socket) + `sandbox-gateway` (registry-only egress proxy, preview ports on 127.0.0.1:41000-41009). Non-root, no capabilities, read-only root, CPU/memory/PID/time limits, internal networks, throwaway Postgres/Redis/MySQL/Mongo. Limits and allowlist in `config/sandbox.yaml`. |
| 4. Previews | Web previews (forwarded ports) and an interactive terminal preview (xterm.js). Sandbox panel on the project home (status, Build/Test/Lint/Run, live output, results); Preview tab in project chats. |
| 5. Templates | `cli-python`, `api-go`, `web-react-ts`, `web-react-js`, `cli-cpp`, each with a manifest, guide and Graphify setup. Creating a project from a template comes with Phase 13 (New app). |

### Acceptance results (2026-10-28, live on the running stack)

| Check | Result |
|---|---|
| Golden tests on fixtures for every pack | ✅ `agent/tests/language_packs/` (fixtures: `python_fastapi`, `go_gin`, `ts_next`, `js_express`, `cpp_cmake`). |
| GoShop builds, tests and runs in the sandbox, visible in Preview | ✅ Build: Go 4.5 s, web 37 s. Tests: **342 Go + 7 Vitest passed**. Run: Postgres (migration applied) + Redis; API on :41000 (`/health`, `/api/v1/products` → 200), web app on :41001 with `/api` passed through to the API. |
| C++ CMake fixture builds, tests pass, runs in the terminal preview | ✅ ctest **2 passed**; typed `5`, `37`, `abc`, `quit` → `total = 5`, `total = 42`, `not a number`, `bye, total 42`, exit 0. |
| Java/PHP declined with a suggestion | ✅ "…in Java with Spring Boot" → "I can do it in Go, TypeScript, Python (closest first)". |
| `make check` | ⚠️ lint, format, mypy clean; pytest **194 passed, 1 failed, 6 skipped**. The failure (`test_settings.py::test_switch_profile_and_replace_the_url`) only happens in the full run; it passes alone (3/3) and with the other API tests (42 passed). Not looked into yet. |
| UI reviewed by you | ⏳ |

Notes: the API preview shows GoShop's own 404 at `/` (it has no handler there; `/health` works). Docker's
`no-new-privileges` is off because it breaks every exec on this host (ADR 0020).

## Phase 4: Graphify, knowledge graph, code search, done (ADR 0019)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 4.

| Task | Result |
|---|---|
| 1. Graphify wrapper | `agent/graphify`: Graphify 0.9.88 offline (tree-sitter, no LLM), built after every import and on request; versions per project with diff and graph checks (empty files, isolated modules, two-way dependencies); `explain` / `query` / `path` through `/api/projects/{id}/graph/ask`. |
| 2. Enrichment | Module edges carry their sources with a confidence: Graphify links and git co-change. |
| 3. Code search | `code_chunks` (migration 0008): masked 60-line chunks, full-text now, vectors when the embedding server is up. `/api/projects/{id}/search`. Project chats get the module map and the best 3 hits. |
| 4. Graph tab + explorer | Graph tab in project chats (modules named in the last reply highlighted), graph card on the project home, full-screen explorer with filter, "hide tests/scripts", module details (depends on / used by / files), graph checks and code search. |
| 5. Live build graph | Throttled updates (≤ 1 per 3 s) streamed as diffs; new / changed / removed colors, "being worked on" ring, stable positions, timeline slider with Live. Demo: `docker compose exec api python -m codewright_api.demo_build <folder>`. |

### Acceptance results (2026-10-27)

| Check | Result |
|---|---|
| GoShop graph shows user, product, order, payment, notification and their links | ✅ 27 modules, 93 links; e.g. payment → order (64 refs), order → notification, order → user, order → product, server → all five. |
| Graph queries correct on fixtures | ✅ Tests on a small shop fixture: `explain place_order()` names its calls, `path pay() → notify()` goes through `place_order`, a new file changes the right module and adds a version. |
| Scripted build shows the graph growing live | ✅ 140 GoShop files copied one by one: 14 versions, modules appear green, change orange, the module being written has a blue ring; the timeline scrubs back to any version. |
| `make check` | ✅ pytest **131 passed**, Vitest **21 passed**, lint/types/format clean. |
| UI reviewed by you | ⏳ |

Found on the way: `git log --format=@@` is read by git as a format name and returned nothing (git co-change was
silently empty); fixed with `tformat:`. The remote GPU tunnel (ngrok) returned 404 at the end of the phase, so the last
live chat check couldn't run; the graph and search context it would get was checked directly.

## Phase 3: Projects, uploads, connectors, delivery, done (ADR 0018)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 3.

| Task | Result |
|---|---|
| 1. Projects | New project form: GitHub URL, ZIP upload, local folder (from `LOCAL_SOURCE_DIR`), Google Drive ZIP link, or empty. Imports run in the background. Project home: files, languages, top level, branch, secrets found, instructions, memory, chats, Deliver, "New chat" (chat inside the project), delete (the original is never touched). |
| 2. Uploads | Clip button in the composer; files are stored, secret-scanned and attached to the message. Text goes to the model masked and cut to fit; the chip says how many secrets were masked. |
| 3. Workspace manager | `workspaces/<id>/source` (original) + `work/` (git repo, changes on branches); GitHub clones keep their history for pull requests. |
| 4. Output connectors + Deliver | ZIP download, copy to the deliveries folder, GitHub pull request on a `codewright/<time>` branch, Drive upload. Pick several at once; one result line each. |
| 5. `project_manage` | Chats in a project get its summary, instructions and memory as context, and its language as the default. |
| Settings | Google Drive connect/disconnect (your own OAuth client, token stored encrypted with `SECRET_KEY`). |

### Acceptance results (2026-10-27)

| Check | Result |
|---|---|
| GoShop connected by each method | ✅ GitHub (`quangdangfit/goshop`: 371 files, Go/TypeScript/SQL, branch `master`), ZIP, local folder. Drive: deferred (you'll set it up later). |
| A sample result delivered to each target | ✅ ZIP (download works) and local folder. GitHub and Drive delivery: deferred (you'll set them up later); the UI says what to set. |
| Malicious ZIP rejected | ✅ `../` paths, absolute paths, symlinks and ZIP bombs refused before anything is written; local paths outside the shared folder refused. |
| Secrets masked | ✅ 8 findings in GoShop (compose file, sample config, README); an uploaded file with a DB password and an API key reached the model as `«secret»` (checked live on the GPU: the answer described the file without the values). |
| `make check` | ✅ pytest **121 passed** (incl. Postgres), Vitest **19 passed**, lint/types/format clean. |
| UI reviewed by you | ⏳ |

## Phase 2: The chat app, done (ADR 0017)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 2.

| Task | Result |
|---|---|
| 1. Conversations | Create, list, search (titles and messages), rename, pin, delete; messages stored as a tree; replies streamed over SSE (`/api/conversations/...`). Chat list in the sidebar, each chat at `/c/<id>`. |
| 2. Intent Router | `agent/chat/router.py`: 20 intents, tiers from `config/tiers.yaml` (new app 1-3 by size, microservices 3), confidence → clarifying question, non-software decline. Slash commands and unsupported languages are decided by rule, without the model (`agent/chat/intents.py`). |
| 3. Missing-info check + Confirm card | `agent/chat/intake.py` + `config/intake.yaml`: required info per intent, at most 3 questions plus the language question for anything new (C18), defaults, two rounds max, then the confirm card. Nothing starts before **Start**. Language answers saved to memory (`memory_items`). |
| 4. Answer playbook | `agent/chat/answer.py`: streamed reply as the Project Manager, last 6 turns as context. |
| 5. In-chat cards | Questions (with "Use the defaults"), Confirm, a small Run card (status, steps, Approve/Reject, link), Done card with guide and next-step chips. Request types whose playbook isn't built yet say which phase builds it. |
| 6. Side panel | Seven tabs, aligned; filled by later phases. |
| 7. Edit / regenerate / branch / stop | Edit adds a sibling (‹ 1/2 › to switch), regenerate, Stop keeps the text so far and cancels the chat's run. Markdown, highlighted code with copy, Mermaid diagrams. |
| 8. Settings | LLM profiles and health (Phase 1), budgets per tier, theme; model picker in the chat header. |

### Acceptance results (2026-10-27, live on your GPU)

| Check | Result |
|---|---|
| Chat works end to end for software Q&A | ✅ Driven in a real browser: streamed answers with code and Mermaid; Java/PHP declined; questions → defaults → confirm → Start; microservices audit run from chat → Done card. |
| Router accuracy | ✅ **118/121 (98%)**, 1.5 s per message (`uv run python -m evals.router --url ...`, cases in `evals/data/router_cases.jsonl`, all of EXAMPLES.md). Misses: photo-rename script → write_code, dark mode → frontend, "clean modules" → refactor. |
| `make check` | ✅ pytest **103 passed**, Vitest **18 passed**, lint/types/format clean. |
| UI reviewed by you | ⏳ |

Fixed on the way: Next.js gzipped the proxied event streams, so the browser saw nothing until a stream ended (also hit
the run page's live output). Compression is off (`next.config.ts`).

## Phase 1: LLM layer and harness core, done (VRAM table pending)

**How to try it:** `docs/E2E-CHECKLIST.md` → Phase 1.

| Task | Result |
|---|---|
| 1. `agent/llm/` | Profiles `remote_gpu` / `local_cpu`, health (now also proves the API key), queue (`max_parallel_llm_jobs`), structured outputs (schema + validation + retry), token/time traces, **budgets** per step and run from `config/budgets.yaml` with a continue/stop prompt. 10 s connect timeout, so a lost server is noticed fast. |
| 2. Remote GPU guide | `docs/setup/remote-gpu.md`: native Windows llama-server, **ngrok with `--api-key-file`** (current), **Tailscale** (recommended long term), SSH. VRAM measurement: `scripts/measure_vram.py` (native, new) or `scripts/measure-vram.sh` (Docker). |
| 3. LangGraph basics | Generic run core in `agent/playbooks/`: registry, `RunState`, tiered plan/result gates (`interrupt()`), Postgres checkpointer, one graph per playbook. Streaming with v2 stream parts: live LLM tokens over SSE (not stored), sub-agent tool calls as team activity. Migration `0004` (runs: validated `inputs`, optional project). `GET /api/playbooks`. |
| 4. `deepagents` | Sample playbook: the Project Manager plans a brief (one structured decision), then delegates to the Business Analyst, who writes `brief.md` into the run workspace. Model calls capped per agent (8 lead / 6 sub-agent). |
| 5. Traces, GPU loss | Every LLM call traced (also agent loops). GPU loss → checkpoint → pause → retry / switch to CPU. |
| Web | Runs page: playbook picker with a form built from the playbook's input schema, tier, model. Run page: timeline from the playbook's flow, plan checklist, artifacts, live output, team activity, gate / GPU / budget cards. |

### Acceptance results (2026-10-27, live on your GPU)

| Check | Result |
|---|---|
| A sample run streams events, pauses for approval, resumes | ✅ 391 live tokens in one run; sub-agent `task` → `write_file /brief.md` in the activity feed; paused at both gates; Edit re-ran the plan with the comment. `brief.md` written 3/3 runs, 13–20 s, 5–6 LLM calls. |
| Crash → resume | ✅ `docker compose kill api` mid-step, then `up`: the run re-ran the interrupted step from its checkpoint and stopped at the gate. |
| Profile switch / GPU loss | ✅ GPU URL pointed at a dead host during the agent step: paused after ~9 s with Retry / Switch to CPU; Retry after restoring finished the step. On `local_cpu` (not running) only Retry is offered. |
| 9B structured-output success rate | ✅ 42/42 valid on the first try, 31/42 correct, 2.2 s per call (`evals/structured_output.py`). |
| `make check` | ✅ ruff, mypy clean; pytest **81 passed** (incl. Postgres); ESLint, tsc, Prettier clean; Vitest **17 passed**; `next build` ok. |
| VRAM vs `num_ctx` | ⏳ Run `python scripts/measure_vram.py …` on the GPU machine (guide section 6) and send the table; `num_ctx` then goes to the largest of 8K–16K that fits (server `-c` and Settings together). |

Bugs found on the GPU and fixed: fields named `title` vanished from grammar schemas; a looping agent overflowed the
4K context; a dead server took 600 s to notice. Details: ADR 0015.

## Reconciliation with CODEWRIGHT.md (v2), done

ADR 0016. Spec files committed (`README.md` untouched); `config/tiers.yaml` has the **20 intents**
(`write_code`, `review_code`, `change_architecture`, `new_app` 1–3); the `microservices` playbook is now
**`architecture_change`** with a `target` input (microservices only, tier 3; other targets in Phases 15–17); `skills/`
and `agent/skills/` folders; Language Packs follow C12 (5 languages); welcome suggestions from `EXAMPLES.md`.
Benchmark candidates are in ADR 0016 for you to choose (nothing cloned).

## Phase 0: done (under README.md; still valid)

| Task | Result |
|---|---|
| 1. Reconcile MonoShift → Codewright | Report approved 2026-10-27. Spec and the uncommitted old-Phase-1 work committed first (nothing lost). Full rename (packages, images, compose project, UI, prompts, docs); env vars without a product prefix and no product name in `.env`; migration `0003` (projects lose `mode`, runs get `playbook` + `tier`); old DB volume removed and recreated. ADR 0012. |
| 2. Repo structure, PROGRESS.md, ADRs | Section 13 layout: `agent/chat`, `agent/playbooks`, `templates/{apps,services,ci,deploy,frontend}`, `evals/{repos,references,tasks}`, `config/{tiers,budgets,noise_rules.default}.yaml` (tiers = the README's 18 intents). ADRs 0012–0014. |
| 3. `deploy/docker-compose.yml` | web, api, postgres (pgvector pg17); optional `ollama-cpu`, `llamacpp-cpu`, `host-llm-bridge`, `langfuse`; new `checks` profile. Project name `codewright` set in the file. |
| 4. FastAPI + Next.js skeletons | FastAPI kept (health, readiness, settings, Alembic). **Chat layout shell** replaces the dashboard: sidebar (New chat, Projects, Chats, Runs, model + health indicator, Settings, theme), chat area (welcome, suggestions, composer), artifacts side panel with Plan/Diff/Graph/Diagram/Tests/Preview/Report tabs. Dark/light, responsive (drawer + overlay panel on phones), skip link, labelled controls. Projects, Runs, Settings stay as full pages. |
| 5. Lint/format/types, pre-commit, CI | Unchanged tooling. **Checks run in Docker** (`make check`); the GitHub workflow is updated but not run (no remote yet, by your choice). |
| 6. `.env.example` | Unprefixed keys, documented; your `.env` migrated with values kept (backup outside the repo). |
| 7. V1–V5 | See below. |

### Acceptance results (2026-10-27, all through Docker)

| Check | Result |
|---|---|
| `docker compose up` works | ✅ postgres, api, web, host-llm-bridge all healthy; `/api/health/ready` → database ok, pgvector ok, migrations `0003` |
| Chat shell renders | ✅ `/` serves the chat shell; `/projects`, `/runs`, `/settings` → 200. Checked with headless Chrome in light, dark and phone width. |
| `make check` | ✅ ruff, ruff format, mypy (60 files): clean. pytest: **54 passed** (incl. Postgres tests on a throwaway `codewright_test` DB). ESLint, tsc, Prettier: clean. Vitest: **16 passed**. `next build`: ok. |
| CI green | ⏸ Not run, by your instruction (no GitHub remote yet). The same checks pass in Docker. |
| V1–V5 reported | ✅ below |

### Verification checklist

| # | Result | Details |
|---|---|---|
| V1 | ✅ Model confirmed | Your remote server (llama.cpp on Windows, via ngrok) serves `Qwen3.5-9B-Q4_K_M.gguf`, 8.95B params, `Q4_K - Medium`. Token streaming works through the tunnel. **Open:** VRAM per `num_ctx` (see Phase 1). |
| V2 | ✅ | Graphify `graphifyy` 0.9.96 now (0.9.95 verified in ADR 0003); interface and 2 gaps unchanged. |
| V3 | ✅ | ADR 0004 + **streaming** (ADR 0014): `astream(stream_mode=["updates","messages","custom"], subgraphs=True, version="v2")`; deep-agent sub-agents appear under `tools:<id>` namespaces. |
| V4 | ✅ Method; one choice open | ADR 0005 (Desktop OAuth). Testing mode (weekly reconnect) vs Production-unverified: decide by Phase 3. |
| V5 | ✅ No blocker | Legacy "CodeWright" editor (Borland era, discontinued); `codewright` taken on PyPI and npm (npm one is an AI spec→code tool); small GitHub repos. Fine for a self-hosted project; trademark search before any public release. ADR 0013. |
| V6 (extra) | ✅ | GoShop has exactly user, product, order, payment, notification + React frontend, Postgres, Redis. ADR 0013. |

## Known issues

- **Your GPU server has no API key yet.** Settings shows a warning for the public ngrok URL. Steps:
  `docs/setup/remote-gpu.md` → Option C (key file, `--api-key-file`, `REMOTE_GPU_API_KEY` in `.env`).
- **Local CPU model server is not running** (nothing on host `127.0.0.1:8080` / `:8081`), so `local_cpu` shows
  *unreachable*. Start your host llama-server; the `host-llm-bridge` picks it up.
- **ngrok URL changes** when ngrok restarts: update it in Settings.
- **Disk:** ~5 GB free (98% used). Enough for rebuilds; needs freeing before benchmarks are cloned.

## Decisions waiting on you

1. Benchmarks: deferred until your own final end-to-end pass (2026-10-29 steer) — pick from ADR 0016's candidates
   then, not now.
2. VRAM table from the GPU machine (sets `num_ctx`) — command is in `docs/setup/remote-gpu.md` Section 6.
3. ~~Google Drive token mode~~ — settled 2026-10-29: keep both `drive.file` + `drive.readonly` scopes (code already
   does this, ADR 0005/0018).
4. GitHub remote — you'll create a private repo and send the URL; add it as a remote and push only after you
   confirm.
