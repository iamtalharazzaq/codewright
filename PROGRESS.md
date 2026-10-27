# Codewright progress

Spec: **`CODEWRIGHT.md`** (v2, single source of truth since 2026-10-27; `README.md` is kept as history). Phase numbers
follow `CODEWRIGHT.md` Section 15.

**Current phase:** Phase 2 (the chat app), done; waiting for your UI review ("next" starts Phase 3: projects, uploads,
connectors, delivery). Phase 1 VRAM table still pending.
**Last updated:** 2026-10-27
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
| GoShop connected by each method | ✅ GitHub (`quangdangfit/goshop`: 371 files, Go/TypeScript/SQL, branch `master`), ZIP, local folder. ⏳ Drive: needs your OAuth client file and `SECRET_KEY` in `.env`. |
| A sample result delivered to each target | ✅ ZIP (download works) and local folder. ⏳ GitHub (needs `GITHUB_TOKEN` and a repo you can push to) and Drive (needs the connection above): both show a clear message about what to set. |
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
- **Disk:** ~6 GB free (98% used). Needs freeing before benchmarks are cloned and sandbox images built (Phase 5).

## Decisions waiting on you

1. Benchmarks: pick from the candidates in ADR 0016 (one per type), after disk space is freed.
2. VRAM table from the GPU machine (sets `num_ctx`).
3. Google Drive token mode (by Phase 3).
4. Sandbox (Phase 5): Docker socket in the API container (simple, root-equivalent) vs rootless Docker / host runner.
5. GitHub remote (you'll share it later).
