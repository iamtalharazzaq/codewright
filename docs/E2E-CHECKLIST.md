# End-to-end checklist

Manual test steps for your own final end-to-end pass (per your 2026-10-29 steer: UI review, the audit review and
the M1 demo are all deferred here, not chased mid-phase). Every feature gets an entry when it's finished: what to
do, what you should see. `PROGRESS.md` has the build/live-run history and a one-line "how to try it" pointer back
to the matching section here.

Not a substitute for the automated tests (`make check`) — this is for a human walking through the app.

## Phase 0: Chat shell
- Run `docker compose up -d --build --wait`. Open `http://localhost:3000`. **Expect:** the chat shell loads (sidebar,
  composer, empty artifacts panel); `/projects`, `/runs`, `/settings` all return 200.

## Phase 1: LLM layer and harness core
- Settings → set your Remote GPU URL and key → **Check connection**. **Expect:** "Ok" with context size and slot
  count.
- Ask anything in a new chat. **Expect:** tokens stream in live.
- Mid-answer, run `docker compose kill api` then `docker compose up -d`. **Expect:** the run resumes from its last
  checkpoint instead of restarting from scratch.
- Point the GPU URL at something unreachable, then ask a question. **Expect:** a pause after ~10s with
  **Retry**/**Switch to local CPU** options.

## Phase 2: Chat app
- Start a new chat, ask a software question. **Expect:** a streamed Markdown answer with highlighted code and
  (when relevant) a Mermaid diagram.
- Ask something in Java or PHP. **Expect:** a decline naming the closest supported language.
- Ask something underspecified (e.g. "add a feature"). **Expect:** 1-3 clarifying questions, then a Confirm card;
  nothing runs before you click **Start**.
- Edit an earlier message. **Expect:** a sibling branch with a ‹ 1/2 › switcher; Stop keeps partial text.

## Phase 3: Projects, uploads, connectors, delivery
- New project → try GitHub URL, ZIP upload, and local folder (from `LOCAL_SOURCE_DIR`). **Expect:** all three import
  and show files/languages/branch on the project home.
- Upload a file containing something that looks like a secret. **Expect:** a chip saying N secrets were masked;
  the model never sees the raw value.
- Try a malicious ZIP (`../` path, absolute path, or a symlink entry). **Expect:** rejected before anything is
  written.
- Deliver a result as a ZIP and to the local folder. **Expect:** both succeed with a result link/path.

## Phase 4: Graphify, knowledge graph, code search
- Open a project's Graph tab. **Expect:** modules and dependency edges render; filters (hide tests/scripts) work.
- Ask "explain `<a real function>`" in a project chat. **Expect:** the answer names its real callers/callees; the
  Graph tab highlights the modules mentioned.
- Run `docker compose exec api python -m codewright_api.demo_build <folder>` against a folder of files added one by
  one. **Expect:** the graph grows live with a timeline slider you can scrub back on.

## Phase 5: Language Packs + sandbox
- Open a Go, Python, TypeScript, JavaScript or C++ project's home. **Expect:** a Sandbox panel with Build/Test/
  Lint/Run buttons and live output.
- Run Build+Test on each of the 5 languages. **Expect:** real pass/fail counts, not placeholders.
- Run a web app. **Expect:** a Preview tab with a working forwarded port. Run a CLI app. **Expect:** an interactive
  terminal preview (xterm.js) you can type into.

## Phase 6: Explain, Audit, Docs, Review, Skills
- Ask a question about a connected project's code. **Expect:** an answer grounded in the real code, "not found"
  when nothing matches, and a diagram tab for anything with steps.
- `/audit` on a project. **Expect:** an As-Is view (C4, deps, DB map, hotspots) with a **Confirm As-Is** gate, then
  security/quality/recommendations and a `audit.md` + `findings.json` in Report.
- On the As-Is gate, correct a fact ("X also calls Y"). **Expect:** a Save/Discard card; Save redraws the diagram
  and the fact persists in project memory.
- `/docs` on a project. **Expect:** README/API/architecture/runbook, an approval gate, then a commit on a
  `codewright/docs-*` branch.
- `/review-code <file>`. **Expect:** findings with severity, each quoting real code from that file, a score, and a
  top-3 summary.
- In a chat, say "save this as a skill". **Expect:** a draft card → Save → it appears in Skills (disabled until
  you enable it) and future matching requests show "Using skill: ...".
- Real-sandbox-verified (`agent/tests/playbooks/test_code_review_sandbox.py`, `make check-sandbox`): `/review-code`
  on the shared `mini_apps/python` fixture, scoped to its one file — real scope/lint/report, a scripted review
  finding on the fixture's known `avg()` bug. Python only; found and fixed a real bug in the shared test harness
  along the way (`.lint()`/`.sandbox()` were returning the wrong output shape — see PROGRESS.md's Retrofit
  section, Phase 6).

## Phase 7: Verification engine
- Tests tab → **Characterize** then **Record** on a running project. **Expect:** a recorded set of journeys.
- **Replay** the same recording. **Expect:** a differences table split into regression/noise/intended, 0
  regressions on an unmodified app.
- **Bench**. **Expect:** before/after latency deltas (or an honest "not measured" if a rate limiter blocks it).
- **Screens** (needs the `browser` sandbox image built — `make sandbox-images`). **Expect:** a screenshot grid with
  diff overlays and an "accept as baseline" button.
- **Record-live** then browse the running app. **Expect:** a live-recorder banner with a Stop button, then a usable
  recording.
- **Real-sandbox retrofit:** replay against a really running preview is verified by `make check-sandbox-host`
  (`agent/tests/playbooks/test_replay_sandbox.py`; previews publish on the host's `127.0.0.1` only, so it runs on the
  host network). The recorder, bench and screens are not covered.

## Phase 8: Write code, fix and test
- Ask to write a small function from scratch (no project). **Expect:** code + tests run in a throwaway sandbox,
  an explanation, one approval, optional commit into a project.
- `/fix-bug` on a project with a known failing test. **Expect:** the right file found, a regression test, a fix,
  and a Tech Lead review before the branch is created.
- `/write-tests <target>`. **Expect:** before/after passing-test counts, no regressions, files that never pass
  dropped and reported honestly.
- **Real-sandbox retrofit:** all three playbooks are real-verified on all 5 languages (`make check-sandbox`):
  `write_code` (`test_write_code_sandbox.py`), `bug_fix` (`test_bug_fix_sandbox.py`,
  against the shared mini-apps' real `avg()` bug) and `tests` (`test_tests_sandbox.py`, a new
  `word_count` empty-string test). Only the model is scripted; the toolchain runs for real. See
  PROGRESS.md's Retrofit section for what this found and fixed along the way.

## Phase 9: Refactor and performance
- `/refactor <folder>`. **Expect:** a plan gate, then a refactor with tests+replay verification; a failed refactor
  is undone, not left half-done.
- `/improve-performance`. **Expect:** a baseline (k6), a found issue with a plan gate, an optimization, and either
  a real before/after number or an honest "not measured" (e.g. if a rate limiter blocks the benchmark).
- **Real-sandbox retrofit:** both playbooks are real-verified on all 5 languages (`make check-sandbox`,
  `test_refactor_sandbox.py`, `test_performance_sandbox.py`). Only the model is scripted.

## Phase 10: Security, upgrade, database change
- `/security-review`. **Expect:** secrets/lint/dependency findings grounded in real code; asking it to fix is a
  separate approval (plan → fix → tests → replay → rescan).
- `/upgrade`. **Expect:** one outdated package at a time, each its own commit, an exact revert if the bump breaks
  tests.
- `/database-change` (e.g. "add an index on X"). **Expect:** a numbered migration + rollback, tried on a throwaway
  Postgres (up/down, row counts, checksums, query plan before/after).
- **Real-sandbox retrofit:** `security` is real-verified on all 5 languages (`make check-sandbox`,
  `test_security_sandbox.py`) and `upgrade` on TypeScript (`test_upgrade_sandbox.py`) — found and fixed a real bug
  where Node/TS outdated-dependency detection silently found nothing. `db_change` is not retrofitted yet (needs a
  scratch-Postgres harness extension). See PROGRESS.md's Retrofit section for details.

## Phase 11: Add a feature
- Ask for a feature "like an existing one" in a project with a similar feature already. **Expect:** a plan that
  names the analog and follows its real files; approval gate; build; a migration that applies and rolls back; 0
  replay regressions before it's offered for approval.
- Cancel a run partway through. **Expect:** unfinished changes are stashed, the project returns to its branch
  cleanly.
- **Real-sandbox retrofit:** real-verified on Python (`make check-sandbox`, `test_feature_sandbox.py`) — survey,
  design, build (real Reflection loop), verify and publish all run for real against the shared mini-app fixture.

## Phase 12: Frontend modernize & DevOps deploy
- `/frontend-modernize` on a React+Vite app. **Expect:** survey → plan gate → a Next.js App Router migration with
  before/after screenshots for parity, kept only if build+tests+replay+screenshots all hold.
- `/devops-deploy` ("Dockerize this and set up CI"). **Expect:** a Dockerfile+`.dockerignore` per component, a
  Compose file with any databases it depends on, and a CI workflow built from the pack's own build/lint/test steps
  — card says images aren't actually built (no Docker daemon in the sandbox).

## Phase 13: New app
- Ask for a new small app in each of the 5 languages (e.g. "a terminal calculator in Python/Go/TypeScript/
  JavaScript/C++"). **Expect:** the right stack picked for the kind of app (don't expect a web app for a CLI
  request), a size-appropriate number of approval gates, and either a green build or an honest red one with the
  real failing tests shown.
- On the Done card, try each delivery target (ZIP, local folder, GitHub PR, Drive folder/ZIP). **Expect:** each
  one-result-line confirms where it landed.
- Ask for a small app ("Make a simple calculator"). **Expect:** dropdowns for Which language?, Which platform? and
  Which frontend? (not for a terminal/API app), two to a row, then one dropdown with checkboxes, "Additional things to be added":
  CI workflow, README file, Graphify, Test cases (backend), Test cases (frontend); only backend tests ticked. No
  explanatory text under any field, and the "You get" line of the confirm card lists only what was ticked. Untick everything extra and run: the new project has no `.github/`, no
  `GRAPHIFY.md`/`mcp.example.json`, no `README.md` and no browser-code tests. Tick them: they come back.
- On the Done card of a new app click **Open web view**. **Expect:** the Preview tab opens with a **Run app** button and
  nothing is running until you click it.
- Watch the side panel's **Plan** tab while the questions are open: Product Manager is in progress; after the card
  shows it is done, then your confirmation, then the run's steps. A red build: the chat card says the log is in the
  **Report** tab ("Failures"), where the test and lint output is.
- **Real-sandbox retrofit:** `scaffold` + `verify` on the `cli-python` template are real-verified
  (`agent/tests/playbooks/test_new_app_sandbox.py`, `make check-sandbox`). The model-driven build is not.

## Phase 14: DevOps deploy
- Covered by Phase 12 above (same playbook).

## Phase 15: Architecture change I (design)
- `/architecture-change target=recommend`. **Expect:** a recommended shape with a stated reason, alternatives
  scored, and (if it recommends microservices) a clear justification rather than a default.
- Ask for a typed edit ("move payment to order"). **Expect:** the design updates and re-validates against the
  rules (one DB owner per table, no sync cycles, etc.).
- Real-sandbox-verified (`agent/tests/playbooks/test_architecture_modular_sandbox.py`, `make check-sandbox`): a
  `target=modular_monolith` move on a tiny real Python app, real tests run after it, a real commit lands. Python
  only, one mechanical `move` only (not `expose`, not TypeScript, not the `recommend`/decomposition-engine side).

## Phase 16: Architecture change II (microservices build)
- `/architecture-change target=microservices` on a **Python** project (Go/TS/C++ services are scaffolded only,
  not actually extracted yet). **Expect:** foundation (gateway/broker/auth/events) written, each service group
  built, tested and replay-checked before cut-over; a failing service is undone, not left half-migrated.
- Check the service board card on the run view. **Expect:** each service's state (scaffolded/extracted/cut over)
  is visible.
- **Real-sandbox retrofit:** `foundation` and `build_one` (one Python service extraction) are real-verified
  (`agent/tests/playbooks/test_architecture_foundation_sandbox.py`, `make check-sandbox`): files written and
  committed, the service extracted behind an ACL, real tests green. Red/undo paths and non-Python services are not.

## Phase 17: Architecture change III (merge / serverless / event-driven)
- `target=merge` on a project with an already-extracted service. **Expect:** the service's code is restored into
  the monolith, its gateway route and runbook removed.
- **Real-sandbox retrofit:** `merge` is real-verified on Python (`make check-sandbox`,
  `test_architecture_merge_sandbox.py`) — found and fixed two real bugs: a dangling shim test left behind after
  every real merge, and `__pycache__` breaking `git add -A` (and never being excluded from real commits at all).
  `serverless`/`event_driven` and the other 4 languages are not retrofitted.
- `target=serverless` on a Python project. **Expect:** stateless entry points packaged per function with a deploy
  manifest template; the monolith's own copy is left untouched.
- `target=event_driven`. **Expect:** a generated `EVENT_REWRITE_REVIEW.md` naming every call site a human should
  turn into a `publish()` call — it won't rewrite the call site itself.

## Phase 18: Translate
- `/translate-language` on a small CLI or HTTP component, picking a different one of the 5 languages as target.
  **Expect:** survey → plan gate → unit-by-unit translation → the same black-box cases checked against the
  translated build → review → approval gate → a new commit under `translated/<package>-<pack>/`, original
  untouched.
- **Real-sandbox retrofit:** real-verified on two language pairs (`make check-sandbox`,
  `test_translate_sandbox.py`) — Python→C++ and Go→Python.

## Phase 19: Deepen the Language Packs (complete for this pass)
- Create or open a C++ project with a `conanfile.txt` (e.g. requiring `nlohmann_json`). Run Build. **Expect:** an
  `install` step runs `conan install` before `configure`, dependencies resolve, and the build actually succeeds
  in the real sandbox (this is real-sandbox-verified this session — `test_cpp_conan_fixture_builds`).
- Create or open a C++ project with a `vcpkg.json` manifest. **Expect (once vcpkg is added to the sandbox image —
  not yet done):** `configure` picks up the vcpkg toolchain file and resolves dependencies during that step.
  Until then, the plan is correct but won't actually build (no vcpkg binary in the sandbox).
- `/audit` or ask a question on a Django + DRF project with a `ModelViewSet` registered on a router. **Expect:**
  the graph/explain answer shows the real REST routes (list/create/retrieve/update/partial_update/destroy, plus
  any `@action`-decorated ones) attributed to the ViewSet, not just the bare `path()`/`include()` lines.
- `/audit` or ask a question on a NestJS project (`@Controller`/`@Get`/`@Post`) or a Go project using Echo
  (`e.GET(...)`, `e.Group(...)`). **Expect:** routes show up in the graph same as Express/Gin do.
- If you ever see a real Conan build fail with a CMake "Imported target ... includes non-existent path" error:
  that was an infra bug (fixed this session) where the `cpp` sandbox toolchain had no persistent cache mount for
  `~/.conan2`, so packages installed in one step vanished before the next step ran. Should not recur.
- Open a Go project and run Lint. **Expect:** `vet`, `staticcheck`, then `gofmt` all run; `staticcheck` is optional
  (a failure is reported but doesn't fail the lint action, same as C++'s `clang-tidy`). Sanity-checked for real this
  session with `docker run` against the rebuilt `codewright-sandbox-go:dev` image on the `go_gin`/`go_echo`
  fixtures: clean (no findings) on both.
- On a C++ project with a `conanfile.txt`, ask Codewright to upgrade one of its pinned dependencies (e.g. bump
  `nlohmann_json` to a newer release). **Expect:** the pin in `conanfile.txt` is rewritten in place (same pattern as
  Python's `requirements.txt` bump), then a rebuild with the new pin succeeds. Not yet wired into the `/upgrade`
  chat flow itself (that playbook is out of scope for this worktree) — this is the Language Pack capability
  (`CppPack.outdated_steps`/`upgrade_steps`) the playbook would call, proven directly: `test_cpp_conan_upgrade_path`
  (fast) and `test_cpp_conan_upgrade_bumps_and_rebuilds` (`pytest.mark.sandbox`, bumps the existing
  `cpp_cmake_conan` fixture's `nlohmann_json` pin from 3.11.3 to the real 3.12.0 release and rebuilds it for real).
- vcpkg is still not installed in the sandbox image: disk was checked at the start of this session (17GB free
  after a `docker system/image/builder prune`, on a box with a 15GB floor) and wasn't comfortably clear of the
  floor, so the vcpkg bootstrap (git clone + build, a few hundred MB plus headroom for churn) was skipped again,
  per this session's own instructions. The `cpp_cmake_vcpkg` fixture's plan is still correct but still won't
  actually build until vcpkg lands in `sandbox/images/cpp.Dockerfile`.
- Entries added here as each further piece of framework/template/linter coverage lands — see PROGRESS.md's Phase
  19 section for what's done so far.

## Known gaps of the real-sandbox retrofit (deferred or out of scope, on purpose)
- Phases 12 and 14 (DevOps deploy): need live testing. Phase 4: not a LangGraph playbook.
- Phase 16: red/undo path, `finalize`, non-Python services, DB split.
- Phase 10: `upgrade` for Python, Go and C++; `db_change`. Phase 15: TypeScript moves. Phase 13: model-driven nodes.
- Phase 7: recorder, bench and screens.
