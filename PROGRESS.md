# Codewright progress

Spec: **`CODEWRIGHT.md`** (v2, single source of truth since 2026-10-27; `README.md` is kept as history). Phase numbers
follow `CODEWRIGHT.md` Section 15.

**Current phase:** Phase 5 (Language Packs + sandbox), done; waiting for your UI review ("next" starts Phase 6:
Explain, Audit, Docs, Review, Skills). Phase 1 VRAM table still pending.
**Last updated:** 2026-10-28
**Branch:** `codewright-phase-0`

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
