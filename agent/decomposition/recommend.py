"""Architecture recommendation ("what should this project be?"): the simplest target that fits, with the reasons for
it and for each target that was passed over (CODEWRIGHT.md Section 5.18).

Rule-based on the module graph and on the goals the user wrote: each target gets a fit from 0 to 10 and reasons;
the recommendation is the highest fit, and a simpler target wins a tie. Microservices must earn their cost: they need
a stated reason (scale, team autonomy, independent releases) AND a graph that splits cleanly.
"""

from __future__ import annotations

import re
from typing import Any

from agent.decomposition.engine import DEFAULT_OPTIONS, Options, alternatives, is_frontend
from agent.decomposition.layers import layer_design

# Simplest first: the tie-break.
TARGETS = ("modules", "modular_monolith", "merge", "event_driven", "serverless", "microservices")
LABELS = {
    "modules": "Clean modules / layers",
    "modular_monolith": "Modular monolith",
    "merge": "Merge services into one app",
    "event_driven": "Event-driven",
    "serverless": "Serverless for the background parts",
    "microservices": "Microservices",
}
GOAL_WORDS = {
    "scale": {"scale", "scaling", "traffic", "load", "throughput", "autoscale", "growth"},
    "autonomy": {"autonomy", "teams", "independent", "independently", "ownership", "deploy", "deployment", "releases"},
    "maintainability": {
        "maintainable",
        "maintainability",
        "clean",
        "messy",
        "tangled",
        "spaghetti",
        "readable",
        "structure",
        "modular",
        "modularity",
        "layers",
        "boundaries",
    },
    "cost": {"cost", "cheaper", "simplify", "simpler", "fewer", "operate", "ops", "overhead"},
    "async": {"async", "events", "event", "decouple", "decoupled", "queue", "queues", "integration", "publish"},
    "jobs": {"jobs", "cron", "scheduled", "webhook", "webhooks", "serverless", "lambda", "functions"},
}
JOB_WORDS = {"job", "jobs", "worker", "workers", "cron", "webhook", "webhooks", "lambda", "scheduler", "tasks"}
FANOUT_WORDS = {"notification", "notifications", "email", "mail", "audit", "search", "indexer", "analytics"}


def goals_in(request: str) -> set[str]:
    words = set(re.findall(r"[a-z]+", request.lower()))
    return {goal for goal, vocab in GOAL_WORDS.items() if words & vocab}


def _words(module: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", module.lower()) if w}


def recommend(  # noqa: PLR0912, PLR0915  (one block of rules per target)
    graph: dict[str, Any], request: str = "", options: Options = DEFAULT_OPTIONS
) -> dict[str, Any]:
    """`{"target", "label", "why", "considered": [{"target", "label", "fit", "reasons"}], "facts"}`"""
    goals = goals_in(request)
    nodes = [n for n in graph["nodes"] if not is_frontend(n)]
    modules = len(nodes)
    files = sum(n.get("file_count", 0) for n in nodes)
    layered = layer_design(graph)
    cycles = len(layered["cycles"])
    best, _ = (
        alternatives(graph, options=options) if modules >= 2 else ({"score": 0, "modularity": 0.0, "groups": []}, [])
    )
    backend_groups = sum(g["kind"] == "backend" for g in best["groups"])
    splits_cleanly = best["modularity"] >= 0.2 and backend_groups >= 3
    service_dirs = [n["id"] for n in nodes if n["id"].startswith("services/")]
    jobs = [n["id"] for n in nodes if _words(n["id"]) & JOB_WORDS]
    callers: dict[str, set[str]] = {}
    for e in graph["edges"]:
        if e.get("weight", 0) > 0:
            callers.setdefault(e["target"], set()).add(e["source"])
    fanout = [n["id"] for n in nodes if _words(n["id"]) & FANOUT_WORDS and len(callers.get(n["id"], ())) >= 2]
    facts = {
        "modules": modules, "files": files, "cycles": cycles, "layer_violations": len(layered["violations"]),
        "cohesive_groups": backend_groups, "design_modularity": best["modularity"], "goals": sorted(goals),
        "service_dirs": len(service_dirs), "job_modules": jobs, "fan_out_modules": fanout,
    }  # fmt: skip

    fit: dict[str, tuple[int, list[str]]] = {}

    def give(target: str, points: int, reason: str) -> None:
        old = fit.get(target, (0, []))
        fit[target] = (old[0] + points, [*old[1], reason])

    # Clean modules: always possible; best when the code is small or its problem is mess rather than size.
    give("modules", 5, "Works for any project and changes nothing at runtime.")
    if modules <= 4 or files < 40:
        give("modules", 3, f"Small project ({modules} modules, {files} files): structure is what it needs.")
    if layered["violations"]:
        give("modules", 2, f"{len(layered['violations'])} dependency(ies) point the wrong way between layers.")
    if "maintainability" in goals:
        give("modules", 1, "You asked for a cleaner structure.")
    # Modular monolith: one deployable app, real boundaries.
    give("modular_monolith", 4, "One app to run and deploy, with boundaries the code enforces.")
    if modules >= 5:
        give("modular_monolith", 2, f"{modules} modules are enough to need strict boundaries.")
    if cycles or "maintainability" in goals:
        give(
            "modular_monolith",
            2,
            "Modules depend on each other in loops or you want clear ownership."
            if cycles
            else "You asked for clear modules.",
        )
    if goals & {"scale", "autonomy"} and not splits_cleanly:
        give(
            "modular_monolith",
            2,
            "Scale or team goals, but the code doesn't split cleanly into services yet: modules come first.",
        )
    if modules <= 2:
        give("modular_monolith", -3, "Too few modules for module boundaries to matter.")
    # Microservices: must be justified.
    if goals & {"scale", "autonomy"}:
        give("microservices", 4, "You want to scale parts separately or let teams release independently.")
    else:
        give("microservices", 0, "No goal in the request needs separate deployments (scale, team autonomy).")
    if splits_cleanly:
        give(
            "microservices",
            3,
            f"The code splits into {backend_groups} cohesive groups (modularity {best['modularity']}).",
        )
    elif modules >= 2:
        give("microservices", -2, "The modules are too entangled to split cleanly today.")
    if modules < 8:
        give(
            "microservices", -3, f"Only {modules} modules: the network and deployment cost would outweigh the benefit."
        )
    # Merge: undo over-splitting.
    if len(service_dirs) >= 4 and (cycles or best["modularity"] < 0.2):
        give("merge", 6, f"{len(service_dirs)} services that are tightly coupled: more moving parts than benefit.")
    if "cost" in goals and service_dirs:
        give("merge", 3, "You want fewer moving parts and lower cost.")
    # Event-driven: where one action fans out.
    if fanout:
        give("event_driven", 5, f"{', '.join(fanout)} are called from several places: events would decouple them.")
    if "async" in goals:
        give("event_driven", 3, "You asked for decoupling or events.")
    # Serverless: only the background parts.
    if jobs:
        give("serverless", 4, f"{', '.join(jobs)} look like background work that suits functions.")
    if "jobs" in goals:
        give("serverless", 3, "You asked about jobs, webhooks or functions.")
    for target in TARGETS:
        fit.setdefault(target, (0, ["Nothing in the project or the request points to it."]))
        fit[target] = (max(0, min(10, fit[target][0])), fit[target][1])
    ranked = sorted(TARGETS, key=lambda t: (-fit[t][0], TARGETS.index(t)))
    top = ranked[0]
    why = [*fit[top][1]]
    if top != "microservices" and fit["microservices"][0] < 6:
        why.append("Microservices are not recommended: " + fit["microservices"][1][-1])
    return {
        "target": top,
        "label": LABELS[top],
        "why": why,
        "considered": [{"target": t, "label": LABELS[t], "fit": fit[t][0], "reasons": fit[t][1]} for t in ranked],
        "facts": facts,
    }
