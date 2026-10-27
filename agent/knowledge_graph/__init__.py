"""The project knowledge graph (CODEWRIGHT.md Section 8.2) at module level.

Graphify gives thousands of symbols; people and a 9B model need the modules (`internal/order`, `web/src`) and how
they depend on each other. Each module edge keeps where its evidence comes from (`sources`, with a confidence), so
later enrichers (runtime calls, table reads/writes, user corrections) add to the same edges.
"""

from __future__ import annotations

import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from agent.tools.secrets import SKIP_DIRS
from agent.tools.workspace import LANGUAGES, git

ModuleGraph = dict[str, Any]  # {"nodes": [...], "edges": [...]}

# Folders that hold modules rather than being one: `internal/order` is a module, `internal` is not.
CONTAINERS = {
    "internal", "src", "pkg", "app", "apps", "lib", "libs", "services", "packages", "modules", "components", "cmd",
}  # fmt: skip
# Structure, not dependency: these relations stay inside a module.
STRUCTURAL = {"contains", "method", "declares"}
IGNORED_TOP = {".github", "graphify-out", "docs"}


def module_of(path: str) -> str | None:
    parts = path.replace("\\", "/").split("/")
    if not path or parts[0] in IGNORED_TOP or any(p in SKIP_DIRS for p in parts):
        return None
    if len(parts) == 1:
        return "(root)"
    if parts[0] in CONTAINERS and len(parts) > 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def module_graph(raw: dict[str, Any]) -> ModuleGraph:
    """Group Graphify's symbol graph into modules and count the dependencies between them."""
    node_module: dict[str, str] = {}
    files: dict[str, set[str]] = defaultdict(set)
    symbols: Counter[str] = Counter()
    for node in raw.get("nodes", []):
        if node.get("file_type") != "code":
            continue
        source = node.get("source_file") or ""
        module = module_of(source)
        if module is None:
            continue
        node_module[node["id"]] = module
        files[module].add(source)
        symbols[module] += 1

    edges: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    confidence: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for link in raw.get("links", []):
        if link.get("relation") in STRUCTURAL:
            continue
        a, b = node_module.get(link.get("source", "")), node_module.get(link.get("target", ""))
        if a is None or b is None or a == b:
            continue
        edges[(a, b)][link.get("relation", "uses")] += 1
        confidence[(a, b)][link.get("confidence", "EXTRACTED")] += 1

    nodes = []
    for module in sorted(files):
        langs = Counter(LANGUAGES.get(Path(f).suffix.lower(), "") for f in files[module])
        langs.pop("", None)
        nodes.append(
            {
                "id": module,
                "label": module.rsplit("/", 1)[-1],
                "files": sorted(files[module])[:200],
                "file_count": len(files[module]),
                "symbols": symbols[module],
                "languages": dict(langs.most_common()),
            }
        )
    return {
        "nodes": nodes,
        "edges": [
            {
                "source": a,
                "target": b,
                "weight": sum(rel.values()),
                "relations": dict(rel),
                "sources": [{"source": "graphify", "confidence": confidence[(a, b)].most_common(1)[0][0]}],
            }
            for (a, b), rel in sorted(edges.items())
        ],
    }


# ── enrichment ───────────────────────────────────────────────────────────────
def git_cochange(work: Path, max_commits: int = 500) -> Counter[tuple[str, str]]:
    """Modules changed in the same commit, a hint of hidden coupling. Empty for a shallow clone or a new repo."""
    try:
        log = git(work, "log", f"-{max_commits}", "--name-only", "--format=@@", check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    for commit in log.split("@@"):
        modules = sorted({m for f in commit.split() if (m := module_of(f)) is not None})
        if len(modules) > 8:  # a sweeping change says nothing about coupling
            continue
        for i, a in enumerate(modules):
            for b in modules[i + 1 :]:
                pairs[(a, b)] += 1
    return pairs


def enrich(graph: ModuleGraph, work: Path) -> ModuleGraph:
    """Add evidence from other sources to the module edges. Today: git co-change (min. 3 shared commits)."""
    known = {n["id"] for n in graph["nodes"]}
    by_pair = {tuple(sorted((e["source"], e["target"]))): e for e in graph["edges"]}
    for (a, b), count in git_cochange(work).items():
        if count < 3 or a not in known or b not in known:
            continue
        confidence = round(min(1.0, count / 10), 2)
        edge = by_pair.get((a, b))
        if edge is None:
            edge = {"source": a, "target": b, "weight": 0, "relations": {}, "sources": []}
            graph["edges"].append(edge)
            by_pair[(a, b)] = edge
        edge["sources"].append({"source": "git_cochange", "confidence": confidence, "commits": count})
    return graph


# ── diff and hygiene ─────────────────────────────────────────────────────────
def _edge_key(e: dict[str, Any]) -> str:
    return f"{e['source']}->{e['target']}"


def diff(before: ModuleGraph | None, after: ModuleGraph) -> dict[str, list[str]]:
    """What changed between two module graphs, for coloring (new / changed / removed)."""
    old = {n["id"]: n for n in (before or {}).get("nodes", [])}
    new = {n["id"]: n for n in after["nodes"]}
    old_edges = {_edge_key(e) for e in (before or {}).get("edges", [])}
    new_edges = {_edge_key(e) for e in after["edges"]}
    changed = [
        m for m in new if m in old and (new[m]["files"] != old[m]["files"] or new[m]["symbols"] != old[m]["symbols"])
    ]
    return {
        "added": sorted(set(new) - set(old)) if before else sorted(new),
        "changed": sorted(changed),
        "removed": sorted(set(old) - set(new)),
        "edges_added": sorted(new_edges - old_edges),
        "edges_removed": sorted(old_edges - new_edges),
    }


def hygiene(raw: dict[str, Any], graph: ModuleGraph, work: Path) -> dict[str, Any]:
    """Checks that the graph is usable: code files Graphify found nothing in, isolated modules, mutual dependencies."""
    seen = {n.get("source_file") for n in raw.get("nodes", []) if n.get("file_type") == "code"}
    code_files = [
        str(p.relative_to(work))
        for p in work.rglob("*")
        if p.is_file() and p.suffix.lower() in LANGUAGES and module_of(str(p.relative_to(work))) is not None
    ]
    empty = sorted(f for f in code_files if f not in seen)
    linked = {e["source"] for e in graph["edges"]} | {e["target"] for e in graph["edges"]}
    isolated = sorted(n["id"] for n in graph["nodes"] if n["id"] not in linked)
    pairs = {(e["source"], e["target"]) for e in graph["edges"] if e["weight"] > 0}
    mutual = sorted(f"{a} <-> {b}" for a, b in pairs if (b, a) in pairs and a < b)
    return {
        "code_files": len(code_files),
        "files_without_symbols": empty[:50],
        "isolated_modules": isolated,
        "mutual_dependencies": mutual,
    }
