# Graphify: the code graph of {{title}}

This project ships with its code graph (`graphify-out/`), built by [Graphify](https://github.com/safishamsi/graphify)
from the source with tree-sitter (local, no LLM, no network).

## Rebuild

```bash
pip install 'graphifyy[mcp]'     # once
GRAPHIFY_BACKEND=none graphify update . --no-cluster
```

`graphify-out/graph.json` is the graph; the CI workflow rebuilds it on every push so it never goes stale.

## Ask it

```bash
graphify explain <name>          # what a function, type or file does and what it touches
graphify query "how does X work"
graphify path <from> <to>        # how two parts are connected
```

## Connect an AI assistant

`mcp.example.json` runs `graphify-mcp` (stdio) for assistants that speak the Model Context Protocol (Claude Code,
Cursor, Codewright itself); its tools include `query_graph`, `get_node`, `shortest_path` and `get_pr_impact`. Copy it to where your assistant reads MCP servers (for example `.mcp.json`).
