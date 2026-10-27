# 0019: Graphify, the module graph, the live graph and code search

Date: 2026-10-27 · Status: accepted · Phase 4

## Context

CODEWRIGHT.md Phase 4: a Graphify wrapper with versions and hygiene checks, an enrichment framework, code search
(chunks, embeddings, pgvector), a Graph tab and explorer, and a live graph that grows while something is built.
The model is a 9B with a 4K context; the graph has to be small enough for it and for a person.

## Decision

- **Graphify `graphifyy[sql]==0.9.88`**, run as its CLI (`graphify update . --no-cluster --force`) with
  `GRAPHIFY_BACKEND=none`: code is parsed locally with tree-sitter, no LLM, no network. 0.9.88 is the newest release
  older than the 14-day package age rule (0.9.96 is newer). GoShop: 3,451 symbols, 12,217 links in about 4 s; the
  per-file cache makes later updates as fast. `graphify-out/` stays in the work copy (excluded from git) so delivered
  projects carry their graph, as Section 8.2 asks. Queries use Graphify's own `explain`, `query` and `path`.
- **Module graph** (`agent/knowledge_graph`): symbols are grouped by folder into modules (`internal/order`,
  `pkg/redis`, `web`); `contains`/`method`/`declares` links stay inside a module, the rest are counted as
  dependencies. This is what the UI draws and what the chat gets.
- **Enrichment**: every module edge has `sources` with a confidence. Today: Graphify (EXTRACTED/INFERRED) and git
  co-change (modules changed together in at least 3 commits). Later sources (runtime calls, table reads/writes, user
  corrections) add entries to the same list.
- **Versions** in `workspaces/<project>/graph/`: `latest.json` (raw Graphify graph), `v<N>.json` (module graph),
  `versions.json` (index with diff and hygiene). A rebuild that changes nothing adds no version.
- **Hygiene checks**: code files that gave no symbols, isolated modules, modules depending on each other both ways.
- **Live graph**: `POST /api/projects/{id}/graph {paths}` after files are written. Updates are throttled per project
  (at most one every 3 s, one more after a burst), each publishes a `graph` event with the diff on
  `GET /api/projects/{id}/events`; `working` names the modules being written. The UI colors new / changed / removed
  modules, rings the ones being worked on, keeps node positions between versions and has a timeline slider with
  "Live". `codewright_api.demo_build` replays a codebase file by file for the acceptance check.
- **Code search**: 60-line chunks of code/config files, secrets masked, in `code_chunks` (Postgres full-text index
  plus a nullable `vector(1024)` column for Qwen3-Embedding-0.6B). Vector search is used when the embedding server
  answers; otherwise full-text search. The embedder turns itself off after one failure, so a missing server costs one
  quick try.
- **Chat**: in a project, the prompt gets the module map (with dependencies) and the 3 best search hits for the
  question, as data. The Graph tab highlights modules the last reply mentions.
- **Rendering**: Cytoscape.js 3.34.3 (built-in `cose` layout), loaded only in the browser.

## Consequences

- Graphify (with its tree-sitter grammars) adds about 200 MB to the API image.
- Semantic search waits for the embedding server (port 8081); until then search is keyword-based but works.
- The module grouping is a heuristic on folder names; it fits Go/Python/TS layouts well and may need a per-language
  rule from the Language Packs (Phase 7).
