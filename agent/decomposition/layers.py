"""Layers for the "clean modules / layered" target: which layer each module belongs to, and which dependencies point the
wrong way. Classic layered rule: a module may depend on its own layer or a layer further in, never outward.

    interface (api, web, handlers, cli)  →  application (services, use cases)  →  infrastructure (db, repositories,
    clients)  →  domain (models, entities: the core, depends on nothing)

A module is placed by the words in its name; a module with no such word is domain (the safe middle for business code)
and is listed as "unplaced" so the user can correct it.
"""

from __future__ import annotations

import re
from typing import Any

LAYERS = ("interface", "application", "infrastructure", "domain")
WORDS: dict[str, set[str]] = {
    "interface": {
        "api",
        "web",
        "http",
        "handler",
        "handlers",
        "controller",
        "controllers",
        "routes",
        "router",
        "cli",
        "cmd",
        "ui",
        "views",
        "rest",
        "grpc",
        "server",
        "endpoints",
    },
    "application": {
        "service",
        "services",
        "usecase",
        "usecases",
        "application",
        "app",
        "workflow",
        "workflows",
        "manager",
        "orchestrator",
    },
    "infrastructure": {
        "db",
        "database",
        "repo",
        "repos",
        "repository",
        "repositories",
        "store",
        "storage",
        "persistence",
        "infra",
        "infrastructure",
        "adapter",
        "adapters",
        "client",
        "clients",
        "cache",
        "queue",
        "migrations",
        "dao",
        "orm",
        "sql",
    },
    "domain": {"domain", "model", "models", "entity", "entities", "core", "types", "schema", "schemas"},
}


def layer_of(module: str) -> tuple[str, bool]:
    """(layer, placed): the layer a module name points to, and whether any word matched."""
    words = {w for part in module.lower().split("/") for w in re.split(r"[^a-z0-9]+", part)}
    for layer in LAYERS:  # most outward first: `api_service` is interface
        if words & WORDS[layer]:
            return layer, True
    return "domain", False


def assign(graph: dict[str, Any]) -> dict[str, str]:
    return {n["id"]: layer_of(n["id"])[0] for n in graph["nodes"]}


def layer_design(graph: dict[str, Any], overrides: dict[str, str] | None = None) -> dict[str, Any]:
    """The To-Be for a layered structure: modules per layer, the dependencies that point outward, the cycles."""
    layers = {**assign(graph), **{m: layer for m, layer in (overrides or {}).items() if layer in LAYERS}}
    unplaced = sorted(n["id"] for n in graph["nodes"] if not layer_of(n["id"])[1] and n["id"] not in (overrides or {}))
    rank = {name: i for i, name in enumerate(LAYERS)}
    bad = [
        {"from": e["source"], "to": e["target"], "from_layer": layers[e["source"]], "to_layer": layers[e["target"]],
         "weight": e["weight"]}
        for e in graph["edges"]
        if e.get("weight", 0) > 0 and not e.get("disputed") and e["source"] in layers and e["target"] in layers
        and rank[layers[e["source"]]] > rank[layers[e["target"]]]
    ]  # fmt: skip
    pairs = {(e["source"], e["target"]) for e in graph["edges"] if e.get("weight", 0) > 0 and not e.get("disputed")}
    cycles = sorted(f"{a} ⇄ {b}" for a, b in pairs if a < b and (b, a) in pairs)
    return {
        "layers": [{"name": name, "modules": sorted(m for m, la in layers.items() if la == name)} for name in LAYERS],
        "assignment": layers,
        "unplaced": unplaced,
        "violations": sorted(bad, key=lambda v: (-v["weight"], v["from"], v["to"])),
        "cycles": cycles,
    }
