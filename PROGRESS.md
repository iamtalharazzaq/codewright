# MonoShift progress

**Current phase:** Phase 0 (project setup), complete and waiting for review ("next").
**Last updated:** 2026-10-26

## How to run

```bash
cp .env.example .env            # set POSTGRES_PASSWORD (any random value: openssl rand -hex 16)
docker compose up -d --build --wait
# Dashboard:  http://localhost:3000
# API docs:   http://localhost:8000/api/docs
# Readiness:  http://localhost:8000/api/health/ready
```

Checks (the same as CI): `make check`. DB tests need `MONOSHIFT_TEST_DATABASE_URL` (see `.env.example`;
`make test-db` creates the throwaway database in the compose Postgres).

Optional compose profiles: `llamacpp-cpu` (bundled llama.cpp serving a GGUF from `MONOSHIFT_MODELS_DIR`, read-only,
nothing copied), `ollama-cpu`, `langfuse`.

## Phase 0: done

| Task | Result |
|---|---|
| 1. Repo structure, PROGRESS.md, ADRs | Section 10 layout (empty folders for later phases hold `.gitkeep`), ADRs 0001–0006 |
| 2. `deploy/docker-compose.yml` | postgres (pgvector pg17), api, web; profiles `llamacpp-cpu`, `ollama-cpu`, `langfuse` (separate file). All ports on 127.0.0.1. Health checks on every service. |
| 3. FastAPI skeleton | `/api/health`, `/api/health/ready` (DB, pgvector, migration), `/api/settings` (secret-free view of `config/models.yaml`), `/api/projects`; pydantic-settings; Alembic migration `0001` (pgvector + `projects`); migrations run on container start |
| 4. Next.js skeleton | Next 16.4.1 App Router, Tailwind v4, shadcn/ui (base-nova), brand/status tokens, dark/light/system theme, responsive shell with skip link, Projects page with loading/empty/error states via the `/api` proxy |
| 5. Lint/format/types, pre-commit, CI | ruff, mypy --strict, pytest; ESLint, Prettier, tsc, Vitest; pre-commit hooks; GitHub Actions (api with Postgres service, web, Docker build + smoke test, `pip-audit`, `pnpm audit`) |
| 6. `.env.example` | Every key documented, including later-phase keys (marked) and Langfuse |
| 7. Verification V1–V4 | See below and ADRs 0002–0005 |

### Acceptance results (2026-10-26)

| Check | Result |
|---|---|
| `docker compose up` works | ✅ postgres, api, web all `healthy`; `/api/health/ready` → `{"database":"ok","pgvector":"ok","migrations":"0001"}` |
| Web shows Projects | ✅ http://localhost:3000 renders the Projects page; `/api/projects` through the web proxy → `[]` (empty state) |
| API tests | ✅ 9 passed (6 unit, 3 against real Postgres + pgvector) |
| Web tests | ✅ 4 passed (Vitest); lint, typecheck, Prettier and `next build` clean |
| pre-commit (all files) | ✅ all hooks pass |
| Dependency audits | ✅ `pip-audit` and `pnpm audit --prod`: no known vulnerabilities |
| CI green | ⚠️ Workflow written and every step run locally, but **not yet run on GitHub**: this repo has no GitHub remote yet |
| V1–V4 reported | ✅ below |

### Verification checklist

| # | Result | Details |
|---|---|---|
| V1 | ✅ Exists and should fit | Ollama `qwen3.5:9b-q4_K_M` (6.6 GB) and GGUF `Qwen3.5-9B-Q4_K_M.gguf` (5.29 GiB) both exist. Hybrid architecture: only 8 of 32 layers keep a KV cache (~32 KiB/token), so the estimate at 16K context is ~6.4–6.8 GiB, well under 10 GB. Real RTX 3080 measurement is Phase 1. Local CPU (llama.cpp, already running here): ~4.9 tok/s generation, valid JSON output. Thinking is on by default and must be disabled for structured tasks. ADR 0002. |
| V2 | ✅ With 2 gaps | `graphifyy` / `graphify` / dual Apache-2.0+MIT / `graphify-out/{graph.json,graph.html,GRAPH_REPORT.md}` / all 4 MCP tools exist. Gaps: `get_pr_impact` needs a GitHub PR number (use `graphify affected` for local diffs); Postgres extraction has no column detail (MonoShift introspects columns itself). There's no `build` command (`update`/`extract` instead). Graphify auto-uses cloud API keys if present, so MonoShift runs it with `--code-only` and a scrubbed env. ADR 0003. |
| V3 | ✅ Docs verified | `create_deep_agent(subagents=…, backend=FilesystemBackend(root_dir, virtual_mode=True))`, `interrupt()` + `Command(resume=…)`, `PostgresSaver`/`AsyncPostgresSaver` + `.setup()`. Key rule: a node re-runs from the top on resume, so gates are side-effect-free nodes. A runnable spike opens Phase 1. ADR 0004. |
| V4 | ✅ Method proposed | Desktop-app OAuth client in the user's own Google Cloud project, installed-app flow from Settings, encrypted refresh token, scopes `drive.file` + `drive.readonly`. Apps in "Testing" get **7-day** refresh tokens; see the question below. ADR 0005. |

## Remaining (next phases)

Phase 1: LLM layer (profiles, health check, structured outputs, queue), remote GPU guide + VRAM measurement,
LangGraph skeleton with 10 stub steps and gates, Postgres checkpointer, deepagents PM + one role, SSE, trace store,
GPU-lost handling.

## Known issues

- **Disk space:** the root disk is 99% full (~3 GB free after building the images). Building more images (sandbox
  toolchains in Phase 7, Langfuse) will fail without freeing space. Nothing was deleted.
- **RAM:** ~20 of 23 GB in use, mostly by the host llama-server instances. Don't start the `llamacpp-cpu` or `ollama-cpu`
  profiles while the host llama-server is running: a second 9B model will not fit.
- **Host model server not reachable from containers:** your llama-server binds `127.0.0.1:8080`, so the API container
  can't use it through `host.docker.internal`. To decide in Phase 1 (ADR 0002 lists the options).
- The system `pnpm` (corepack shim at `/usr/local/bin/pnpm`) can't start pnpm 12. Use `corepack pnpm …` (as the
  Makefile and pre-commit do) or `npm i -g pnpm@12.12.1`.
- Starlette warns that its TestClient will move from `httpx` to `httpx2`. Harmless for now.
- Next.js 16.4.0 had critical advisories; upgraded to 16.4.1 as a documented exception to the 14-day rule (ADR 0006).

## Decisions waiting on the user

1. **GitHub remote** for this repo (needed for CI to run on GitHub)?
2. **Langfuse:** kept as an opt-in profile per the README. It needs about 6 extra containers and several GB of disk,
   which is not available right now. Keep it, or drop it in favour of the built-in trace view only?
3. **Remote GPU access:** can this machine reach the RTX 3080 box (tunnel address)? Needed for the Phase 1 VRAM
   measurements. Otherwise I'll provide a script for you to run there.
4. **Local CPU model server:** (a) bind your host llama-server to the Docker bridge so containers can reach it,
   (b) use the bundled `llamacpp-cpu` profile with `/home/ubuntu/models` (and stop the host one), or (c) run the API on
   the host.
5. **Google Drive token lifetime:** Testing mode (re-connect weekly) or "In production", unverified (long-lived)?
6. **Embeddings:** `config/models.yaml` uses `Qwen3-Embedding-0.6B`, already running here on :8081, instead of the
   README's example `nomic-embed-text`. OK?
7. **Sandbox (Phase 7):** mounting the Docker socket into the API container is simplest but effectively root on the
   host. Acceptable, or use rootless Docker / run the sandbox runner on the host?
