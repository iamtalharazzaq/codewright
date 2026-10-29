# Codewright progress

Spec: **`CODEWRIGHT.md`** (v2, single source of truth since 2026-10-27; `README.md` is kept as history). Phase numbers
follow `CODEWRIGHT.md` Section 15.

**Current phase:** Phases 13 (New app) and 15 (Architecture change I) built, not yet run live (nor 11, 12, 14). Phase 16 is next.
Still open: Phase 8's 20-example eval, Phase 6's audit review and M1 demo (with you, deferred to the end), Phase 1 VRAM table.
**Last updated:** 2026-10-29
**Branch:** `codewright-phase-0`

## Resume here (written 2026-10-29, for a new session or account)

Running when this was written (background agents of the previous session; they stop if that session ends, their
files stay on disk in `.claude/worktrees/`):
1. **Phase 16** (microservices build): branch `worktree-agent-a41c939c87c60e480`. When done: merge it into this branch, then update this file.
2. **Live runs of Phases 11 → 12 → 13 → 14 → 15**, one after another (Codewright allows one active run; one GPU). Fixes are committed straight on this branch; the report lists what ran, what broke, what is open.

Then, in this order:
- `python3 evals/write_code.py` (Phase 8: the 20 `EXAMPLES.md` section 2 requests, ~1-2 h on the GPU; run only after the live runs, same single run slot). Write the result into the Phase 8 section.
- Phase 6 audit review and the M1 demo need **you** (see "Decisions waiting on you").
- Next phases: 17 (architecture III), 18 (Translate), 19 (deepen Language Packs/templates), 20 (evals), 21 (polish), 22 (hardening, v1.0).
- One `make check` pass at the end of a batch (project rule: features first, one check pass). Known: `agent/tests/graph/test_graph.py::test_graphify_build_versions_and_queries` fails on the host venv only (Graphify not installed there); ruff reports ~20 long-line errors in `new_app`, `chat.py`, `runs.py` to fix; the web changes (Done card delivery panel, Drive folder/ZIP options) were never type-checked.
- Disk was at 98% (5.6 GB free) after pruning the Docker build cache; old worktrees under `.claude/worktrees/` (about 600 MB) can go once their branches are merged or abandoned.

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

## Phase 15: Architecture change I (ADR 0029; built, not yet run on a real benchmark)

| Task | Result |
|---|---|
| Recommend + To-Be | `target=recommend` picks the simplest target that fits and says why microservices are or aren't justified; a To-Be design for any target with "why this shape", alternatives, events and sagas; typed edits ("move payment to order") re-validate against the rules. |
| Decomposition engine | Louvain grouping of the module graph, merged by rules (one frontend, one owner per table, no sync cycles, chatty pairs merged, no tiny services); scored, alternatives kept. Language Advisor keeps the language unless another clearly wins. |
| Clean modules / modular monolith | Rules + stdlib checker written into the project (`architecture/boundaries.json`, `check_boundaries.py`), existing violations are known debt. Mechanical moves (Python moves + expose; TS/JS moves), one commit each, tests after each, a red move restored exactly, replay at the end. Go/C++ get design and rules, no moves. |
| Behavior | `simulate=True` keeps the old stub steps; microservices conversion is still simulated (Phases 16-17); serverless/event-driven/merge conversion refused up front (designable); a real run needs a project. |

Open (acceptance not demonstrated): a Python benchmark restructured with 0 replay regressions (tested on a small temp repo with a fake replay); GoShop → ~5-service design (fixture gave 4 backend groups + frontend because a shared `db` module joined `product`; real import not run). `test_runs.py`/`test_db.py` edits need Postgres and have not run.

## Phase 13: New app (ADR 0030; `new_app` built, not yet run live)

| Task | Result |
|---|---|
| `new_app` playbook | requirements → [gate] → design → [gate] → [screens → gate] → scaffold → build → verify → review → docs → **approve app** → publish. Small = 1 gate, medium = 2 (plan, app), large = 4 (requirements, design, screens, app). |
| Stack rules | `new_app/stacks.py`: app type → options with one recommended and a reason; the user's language wins; only the 5 languages; unsupported language declined with the closest stack; a missing template falls back and says so. |
| Own project | The app is built in a new project (`create_project`), so Preview/Tests/other playbooks work on it; result card shows red builds as red; GUIDE.md run section comes from the template manifest. |
| Chat | New app inputs and size (from the card's tier) wired in chat; a new app never attaches to the chat's current project; budgets for the playbook. |
| Template library | All 17 templates of CODEWRIGHT.md 8.4 exist (12 added): Next.js sites, 3 full-stack (FastAPI/Go/Node + Next.js + Postgres, auth, CRUD, admin, Compose, CI), cli-go, api-fastapi/node, 4 libraries. Run locally: Go/Python/TS tests, `next build`, the 3 backends against real PostgreSQL. Not run: Docker builds, C++ GoogleTest, sandbox tests, CI. Go templates say go 1.26 (tested at 1.23). |
| Tests | `agent/tests/playbooks/test_new_app.py` (stack rules, a whole small run, red build, gates per size). Targeted tests pass; the full `make check` is the end pass. |

| Where to keep it | The Done card of a new app asks: ZIP download, local folder, GitHub PR, **Google Drive as a folder** or **Drive as one ZIP** (the user picks; the folder is the usual choice). An opt-in box deletes the code from this machine after a successful Drive/GitHub upload (kept if any upload fails; the project stays listed as delivered with the link). |

Open: live runs (tic-tac-toe, calculator in 5 languages, 10 small + 5 medium apps, inventory, clinic); the M3 demo; Preview of
a browser app / terminal app is started from the project's Preview tab, not by the playbook.

## Phases 12 and 14: Frontend and DevOps (ADR 0027, 0028; built, not yet run live)

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

| Task | Result |
|---|---|
| `add_feature` | survey → stories → design → **approve plan** → build → verify → review → **approve result** → publish. Committed only when the tests pass and a new migration applies and rolls back on PostgreSQL; otherwise nothing is kept. |
| Feature by analogy | The model picks the existing feature the new one is like and names it; the plan follows that feature's real files (adapted copies, wiring, appended type declarations, a migration). Left-out files are listed with reasons. |
| Build order | Types, model, migration, repository, service, handlers, tests, then wiring; each file sees the earlier files' declarations; up to 5 fix rounds under feature build rules. |
| Cancel | A cancelled run's unfinished changes are stashed and the project goes back to its branch (all playbooks). |
| Live (GoShop) | GoShop already has a wishlist, so "price alerts" (like the wishlist) was the test. One run went green: 12 files, 350 tests, replay 0 regressions/25, screenshot. Review found its migration lacked the `target_price` column, which led to the migration trial gate; it was not approved. Later runs vary with the 9B model (type mismatches between layers). |

Acceptance still open: a price-alerts run that passes the migration gate and is approved (re-run once the model is stable); acceptance-criteria tests are thin where the analog's tests need generated mocks.

## Phase 10: Security, upgrade and database change (ADR 0025, Milestone M2)

| Task | Result |
|---|---|
| `security_review` | scan (secrets, security lint, dependency audit) → model review → grounded findings; "fix" requests are tier 2 (plan, fix, tests, replay, rescan). Live on GoShop: seeded AWS key found and removed, 349 tests green, replay 0 regressions/25. |
| `upgrade` | outdated direct dependencies → plan → one package at a time (bump, build, test, adapt code if red, exact revert if still red), one commit each. Live on GoShop: grpc and x/crypto bumped, 349 tests, replay 0/25. Release notes are not read, and the brief says so. |
| `database_change` | next numbered migration + rollback → tried on a fresh PostgreSQL sandbox database (up, down, row counts, checksums, schema, query plans). Live on GoShop: index on `products.category_id`, rollback exact, Seq Scan to Index Scan. |
| Model connection | LLM client retries a dropped connection (3 times). |

Known limits: model false positives in the security review (seen once, shown at the gate); PostgreSQL only; no engine changes; C++ has no dependency audit.

## Phase 9: Refactor and performance (ADR 0024)

| Task | Result |
|---|---|
| `refactor` | map → plan → **approve plan** → refactor (Reflection loop, undo on failure) → verify (tests + replay) → review → **approve result** → publish. Live on GoShop `pkg/utils`: 4 files refactored, 349 tests green, replay 0 regressions/25 requests, a real Tech Lead finding, committed on `codewright/refactor-*`. |
| `improve_performance` | baseline (k6) → find (search + static scan for N+1/sleeps/rescans) → **approve plan** → optimize → verify (tests + replay + benchmark) → review → **approve result** → publish. Live on a seeded `time.Sleep` in GoShop's `ListCategories`: found and removed from the code alone, tests green, replay 0 regressions, correctly reported **not measured** instead of a fake number. |
| Finding | GoShop's own per-IP rate limiter throttles k6's benchmark traffic (same source IP) to near-0% success regardless of endpoint. Fixed by having the benchmark recognize a high failure rate as "a guard is rejecting this load" and refuse to report it as latency, rather than bypassing the limiter. |
| `change_core.py` | Shared by both: whole-file rewrites, Reflection loop, undo-on-failure, replay-backed "unchanged behavior". |

Acceptance still open: a repeat with the sandbox's `RATE_LIMIT_REQUESTS` raised, to get a real before/after number (not just "not measured" proven honest).

## Phase 8: Write code, fix and test (ADR 0023)

| Task | Result |
|---|---|
| `write_code` | A playbook now (no project needed): code + tests in a throwaway workspace, run in the real sandbox, Reflection loop (max 5; fixes the tests on attempts 3 and 5), explanation with complexity, one approval, optional commit into a project. Live: palindrome in Python ✅ (13 tests), reverse a linked list in Go ✅ (attempt 4), binary search in C++ ⚠️ failed after 5 attempts (code and tests disagreed on the API) and says so. |
| `fix_bug` | locate → reproduce → fix (Reflection) → Tech Lead review → one approval → branch `codewright/fix-*`. Live on GoShop with a seeded off-by-one in `pkg/paging`: right file, failing regression test, fixed in 1 attempt (1-line diff), 342+ tests green. |
| `write_tests` | targets → tests in Codewright's own file → before/after tests and coverage → one approval → branch `codewright/tests-*`. Live on GoShop `pkg/paging`: 342 → 352 passing, no regressions. Files that never pass are dropped and reported. |
| Reflection loop | `agent/playbooks/reflection.py`, feedback = failing cases + the broken step's key output lines. |
| UI | The Report tab shows diffs and written code; Done cards list the files on the branch. |

Acceptance still open: all 20 `EXAMPLES.md` §2 requests (only 3 run live so far), more seeded bugs, an eval record.

## Phase 7: Verification engine, done (ADR 0022)

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

1. Benchmarks: pick from the candidates in ADR 0016 (one per type), after disk space is freed.
2. VRAM table from the GPU machine (sets `num_ctx`).
3. Google Drive token mode (by Phase 3).
4. GitHub remote (you'll share it later).
