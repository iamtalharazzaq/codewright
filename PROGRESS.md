# Codewright progress

**Current phase:** Phase 0 (setup and reconciliation), complete and waiting for review ("next").
**Last updated:** 2026-10-27
**Branch:** `codewright-phase-0`

## How to run

```bash
cp .env.example .env     # first time only: set POSTGRES_PASSWORD (openssl rand -hex 16) and LLM_REMOTE_GPU_URL
docker compose up -d --build --wait
# Chat app:   http://localhost:3000
# API docs:   http://localhost:8000/api/docs
# Readiness:  http://localhost:8000/api/health/ready
make check               # every lint/type/test check, inside Docker
```

Optional compose profiles: `host-llm-bridge` (reach a llama-server bound to the host's 127.0.0.1; on in `.env`),
`llamacpp-cpu`, `ollama-cpu`, `langfuse`, `checks` (used by `make check`).

## Phase 0: done

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
| V1 | ✅ Model confirmed | Your remote server (llama.cpp on Windows, via ngrok) serves `Qwen3.5-9B-Q4_K_M.gguf`, 8.95B params, `Q4_K - Medium`. Token streaming works through the tunnel. Estimate ~6.5 GiB VRAM at 16K (ADR 0002). **Open:** it runs `n_ctx 4096` (1 slot), below the README's 16K; and VRAM needs `scripts/measure-vram.sh` on the GPU box (Phase 1). |
| V2 | ✅ | Graphify `graphifyy` 0.9.96 now (0.9.95 verified in ADR 0003); interface and 2 gaps unchanged. |
| V3 | ✅ | ADR 0004 + **streaming** (ADR 0014): `astream(stream_mode=["updates","messages","custom"], subgraphs=True, version="v2")`; deep-agent sub-agents appear under `tools:<id>` namespaces. |
| V4 | ✅ Method; one choice open | ADR 0005 (Desktop OAuth). Testing mode (weekly reconnect) vs Production-unverified: decide by Phase 3. |
| V5 | ✅ No blocker | Legacy "CodeWright" editor (Borland era, discontinued); `codewright` taken on PyPI and npm (npm one is an AI spec→code tool); small GitHub repos. Fine for a self-hosted project; trademark search before any public release. ADR 0013. |
| V6 (extra) | ✅ | GoShop has exactly user, product, order, payment, notification + React frontend, Postgres, Redis. ADR 0013. |

## Next: Phase 1, LLM layer and harness core

Much of it exists from the old Phase 1 (LLM client, structured outputs, queue, health, run manager, SSE, traces,
Settings, tool allowlists). Phase 1 reshapes it to the README: generic `RunState` with playbook/tier, a run-subgraph
pattern, budgets from `config/budgets.yaml`, the microservices workflow moved to `agent/playbooks/microservices/`,
streaming per ADR 0014, GPU-loss handling, and the 9B structured-output success rate measured on the remote GPU.
Working order (your preference): functionality first, tests at the end of the phase.

## Known issues

- **Local CPU model server is not running.** Nothing listens on host `127.0.0.1:8080` (model) or `:8081`
  (embeddings), so `local_cpu` shows *unreachable*. Start your host llama-server; the `host-llm-bridge` picks it up.
- **Remote context:** the GPU server runs `-c 4096`; Settings warns because `num_ctx` is 16384. Restart it with
  `-c 16384 -np 1` (docs/setup/remote-gpu.md), or tell me to lower `num_ctx`.
- **ngrok URL changes** when ngrok restarts: update it in Settings (or `LLM_REMOTE_GPU_URL` in `.env`).
- **Disk:** ~8 GB free (97% used). Enough for now; sandbox images (Phase 5) will need more.
- Old items kept for you to decide: Docker volume `monoshift_workspaces` (old stub-run files) and images
  `monoshift-api:dev` / `monoshift-web:dev` (~0.7 GB, superseded).
- `pnpm` via corepack (`corepack pnpm …`) only matters for host runs; `make check` doesn't need it.

## Decisions waiting on you

1. GitHub remote (you'll share it later).
2. Remote GPU context: raise the server to 16K, or lower `num_ctx` to 4096?
3. Google Drive token mode (by Phase 3).
4. Sandbox (Phase 5): Docker socket in the API container (simple, root-equivalent) vs rootless Docker / host runner.
5. Delete `monoshift_workspaces` and the old `monoshift-*` images?
