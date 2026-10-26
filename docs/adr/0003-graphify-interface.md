# 0003. Graphify's real interface (verification V2)

- **Status:** accepted
- **Date:** 2026-10-26
- **Phase:** 0

## Context
README C7/V2/Section 6 assume a PyPI package `graphifyy`, a `graphify` CLI, MCP tools `query_graph`, `get_node`,
`shortest_path`, `get_pr_impact`, and Postgres schema extraction. Verified by reading
https://github.com/safishamsi/graphify and installing `graphifyy[mcp]` 0.9.95 in a scratch venv, then running it on a
tiny Go fixture.

| README assumption | Reality (0.9.95) |
|---|---|
| PyPI `graphifyy`, CLI `graphify` | ✅ Also a `graphify-mcp` entry point. Python ≥ 3.10. Extras: `mcp`, `sql`, `postgres`, `leiden`. |
| License | ✅ Dual Apache-2.0 / MIT. |
| Output files | ✅ `graphify-out/graph.json` (NetworkX node-link: `nodes`, `links`, `hyperedges`, `graph.schema_version`, `graph.graphify_version`), `graph.html`, `GRAPH_REPORT.md`, plus `manifest.json`, `cache/`, label files. |
| Code graph with no LLM | ✅ `graphify update <path>` (AST only) or `graphify extract <path> --code-only`. |
| `build` command | ⚠️ No `build`: use `update` (code) or `extract` (headless full). |
| `query`, `path`, `explain` | ✅ Exit codes 0 = answer, 3 = ambiguous, 4 = no match. Also `affected` (reverse impact), `god-nodes --json`, `cluster-only --resolution`, `merge-graphs`, `export html/svg/graphml/callflow-html`, `hook install`. |
| MCP tools | ✅ `query_graph`, `get_node`, `shortest_path`, `get_pr_impact`; also `get_neighbors`, `get_community`, `god_nodes`, `graph_stats`, `list_prs`, `triage_prs`. Transports: stdio (default) or Streamable HTTP. |
| `get_pr_impact` | ⚠️ Takes a **GitHub PR number** (uses GitHub). It cannot assess a local, not-yet-pushed diff. |
| Postgres schema extraction | ✅ `graphify extract --postgres DSN`: tables, views, functions, FKs. ⚠️ **No column-level detail.** |
| Community output | ✅ Leiden (with the `leiden` extra), else NetworkX Louvain; community id + name on every node. |

Edge records carry `relation`, `confidence` (`EXTRACTED`/…), `confidence_score`, `source_file`, `source_location`.

## Decision
- Pin `graphifyy[mcp,sql,postgres,leiden]` (exact version chosen in Phase 3, at least 14 days old).
- The CLI wrapper uses `update`/`extract --code-only` for builds; no LLM calls from Graphify by default.
- **Privacy guard:** Graphify's semantic pass auto-detects cloud API keys (`GEMINI_API_KEY`, …) from the environment.
  MonoShift runs Graphify with a scrubbed environment and `--code-only`. If semantic extraction or community labeling
  is wanted later, it goes through `--backend openai` + `OPENAI_BASE_URL` pointing at the self-hosted model, with
  `--max-concurrency 1` and a batch size that fits `num_ctx`.
- Tech Lead impact analysis on local diffs uses `graphify affected` + the enriched graph. `get_pr_impact` is only used
  after a PR exists on GitHub.
- Column-level data (Step 3/8) comes from MonoShift's own schema introspection (`information_schema`) and Language
  Packs, not Graphify.

## Consequences
README Section 6.4's tool list is accurate. Two gaps (local-diff impact, columns) are covered by MonoShift code.
