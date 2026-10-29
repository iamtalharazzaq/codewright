"""The decomposition engine (CODEWRIGHT.md Section 5.18, "To-Be"): turn the module graph into groups (the modules of a
modular monolith, or the services of a microservice design), with rules, scores, alternatives and editing.

    weighted module graph:  w = a·static + b·runtime + c·shared_table_writes + d·co_change   (each log-scaled)
      → community detection (Louvain) at several resolutions
      → rules: one frontend, one owner per table, no sync cycles, chatty pairs merged, no nano-services
      → scores, the alternatives that were considered, and a "why this shape" explanation

Everything is plain Python on JSON-friendly data and fully deterministic (nodes are visited in sorted order), so the
same graph gives the same design and a design can be saved in the run state. The model only *names* groups, in the
playbook; nothing here calls it.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

Pair = tuple[str, str]
FRONTEND = "frontend"
FRONTEND_NAMES = {"web", "frontend", "client", "ui", "webapp", "www", "site", "storefront", "dashboard"}
FRONTEND_FILES = {".tsx", ".jsx", ".vue", ".svelte"}
# Where each kind of evidence sits on an edge's `sources` (agent/knowledge_graph), and its count field.
SIGNALS = {
    "git_cochange": ("cochange", "commits"),
    "runtime_calls": ("runtime", "count"),
    "table_writes": ("tables", "count"),
}
RESOLUTIONS = (0.6, 1.0, 1.5, 2.2)


@dataclass(frozen=True)
class Weights:
    """a, b, c, d of the weighted graph."""

    static: float = 1.0
    runtime: float = 2.0
    tables: float = 3.0
    cochange: float = 1.5


@dataclass(frozen=True)
class Options:
    one_frontend: bool = True
    chatty_share: float = 0.75  # two groups that send each other at least this share of their traffic are merged
    min_files: int = 2  # a group with fewer files (and few symbols) is a nano-service
    min_symbols: int = 8
    ideal_groups: int = 5  # only used to prefer a design near this size among near-equal scores


DEFAULT_WEIGHTS = Weights()
DEFAULT_OPTIONS = Options()


def key(a: str, b: str) -> Pair:
    return (a, b) if a <= b else (b, a)


# ── the weighted graph ───────────────────────────────────────────────────────
def pair_weights(graph: dict[str, Any], weights: Weights = DEFAULT_WEIGHTS) -> dict[Pair, float]:
    out: dict[Pair, float] = defaultdict(float)
    for e in graph["edges"]:
        if e.get("disputed") or e["source"] == e["target"]:
            continue
        signals: Counter[str] = Counter()
        signals["static"] = e.get("weight") or (3 if e.get("user_fact") else 0)
        for s in e.get("sources", []):
            if s.get("source") in SIGNALS:
                name, field = SIGNALS[s["source"]]
                signals[name] += s.get(field, 0)
        out[key(e["source"], e["target"])] += sum(getattr(weights, k) * math.log1p(v) for k, v in signals.items())
    return dict(out)


def directed_weights(graph: dict[str, Any]) -> dict[Pair, float]:
    """Who calls whom (static dependencies only), for cycles."""
    return {
        (e["source"], e["target"]): float(e["weight"])
        for e in graph["edges"]
        if e.get("weight", 0) > 0 and not e.get("disputed") and e["source"] != e["target"]
    }


def is_frontend(node: dict[str, Any]) -> bool:
    name = node["id"].lower().split("/")
    if name[-1] in FRONTEND_NAMES or (len(name) > 1 and name[0] in {"apps", "packages"} and name[1] in FRONTEND_NAMES):
        return True
    files = node.get("files") or []
    return bool(files) and sum(f.lower().endswith(tuple(FRONTEND_FILES)) for f in files) * 2 > len(files)


# ── community detection ──────────────────────────────────────────────────────
def louvain(nodes: list[str], pair_w: dict[Pair, float], resolution: float = 1.0) -> list[list[str]]:
    """Louvain modularity optimisation, deterministic. Returns the communities, largest first."""
    adj: dict[str, dict[str, float]] = {n: {} for n in nodes}
    for (a, b), w in pair_w.items():
        if a in adj and b in adj and a != b and w > 0:
            adj[a][b] = adj[a].get(b, 0) + w
            adj[b][a] = adj[b].get(a, 0) + w
    members: dict[str, list[str]] = {n: [n] for n in nodes}
    while True:
        part = _local_moving(adj, resolution)
        if len(set(part.values())) == len(adj):
            break
        merged: dict[str, dict[str, float]] = {}
        new_members: dict[str, list[str]] = defaultdict(list)
        for n, c in part.items():
            new_members[c] += members[n]
            merged.setdefault(c, {})
        for a, nb in adj.items():
            for b, w in nb.items():
                merged[part[a]][part[b]] = merged[part[a]].get(part[b], 0) + w
        adj, members = merged, dict(new_members)
    return sorted((sorted(m) for m in members.values()), key=lambda g: (-len(g), g[0]))


def _local_moving(adj: dict[str, dict[str, float]], resolution: float) -> dict[str, str]:
    degree = {n: sum(nb.values()) for n, nb in adj.items()}
    m2 = sum(degree.values())
    comm = {n: n for n in adj}
    total = dict(degree)
    if m2 == 0:
        return comm
    for _ in range(50):
        moved = False
        for n in sorted(adj):
            old = comm[n]
            total[old] -= degree[n]
            links: dict[str, float] = defaultdict(float)
            for j, w in adj[n].items():
                if j != n:
                    links[comm[j]] += w
            links.setdefault(old, 0.0)

            def gain(c: str, n: str = n, links: dict[str, float] = links) -> float:
                return links[c] - resolution * degree[n] * total[c] / m2

            best = old
            for c in sorted(links):
                if gain(c) > gain(best) + 1e-12:
                    best = c
            comm[n] = best
            total[best] += degree[n]
            moved |= best != old
        if not moved:
            break
    return comm


# ── rules ────────────────────────────────────────────────────────────────────
class Partition:
    """Groups of modules plus the facts the rules read. Rules merge groups and say why."""

    def __init__(self, graph: dict[str, Any], groups: list[list[str]], pair_w: dict[Pair, float]) -> None:
        self.nodes = {n["id"]: n for n in graph["nodes"]}
        self.pair_w = pair_w
        self.directed = directed_weights(graph)
        self.groups = [sorted(g) for g in groups]
        self.log: list[str] = []

    def of(self, module: str) -> int:
        return next(i for i, g in enumerate(self.groups) if module in g)

    def weight(self, a: list[str], b: list[str]) -> float:
        return sum(self.pair_w.get(key(x, y), 0.0) for x in a for y in b)

    def internal(self, g: list[str]) -> float:
        return sum(self.pair_w.get(key(x, y), 0.0) for i, x in enumerate(g) for y in g[i + 1 :])

    def external(self, i: int) -> float:
        return sum(self.weight(self.groups[i], g) for j, g in enumerate(self.groups) if j != i)

    def files(self, g: list[str]) -> int:
        return sum(self.nodes[m].get("file_count", 0) for m in g)

    def symbols(self, g: list[str]) -> int:
        return sum(self.nodes[m].get("symbols", 0) for m in g)

    def merge(self, i: int, j: int, why: str) -> None:
        a, b = self.groups[i], self.groups[j]
        self.log.append(f"{', '.join(_labels(a))} + {', '.join(_labels(b))}: {why}")
        self.groups = [g for k, g in enumerate(self.groups) if k not in (i, j)] + [sorted(a + b)]
        self.groups.sort(key=lambda g: (-len(g), g[0]))

    def group_edges(self) -> dict[tuple[int, int], float]:
        index = {m: i for i, g in enumerate(self.groups) for m in g}
        out: dict[tuple[int, int], float] = defaultdict(float)
        for (a, b), w in self.directed.items():
            if a in index and b in index and index[a] != index[b]:
                out[(index[a], index[b])] += w
        return dict(out)


def _labels(modules: list[str]) -> list[str]:
    return [m.rsplit("/", 1)[-1] for m in modules]


def sync_cycles(edges: dict[tuple[int, int], float], count: int) -> list[list[int]]:  # noqa: PLR0912
    """Strongly connected components with more than one group (Tarjan, iterative)."""
    out: dict[int, list[int]] = defaultdict(list)
    for a, b in edges:
        out[a].append(b)
    index: dict[int, int] = {}
    low: dict[int, int] = {}
    on: set[int] = set()
    stack: list[int] = []
    found: list[list[int]] = []
    counter = 0
    for root in range(count):
        if root in index:
            continue
        work = [(root, iter(sorted(out[root])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(out[w]))))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    if len(comp) > 1:
                        found.append(sorted(comp))
    return found


def table_owners(part: Partition) -> dict[str, list[int]]:
    """Table → the groups that write it (node["tables_written"], from the SQL scan)."""
    writers: dict[str, set[int]] = defaultdict(set)
    for i, g in enumerate(part.groups):
        for m in g:
            for t in part.nodes[m].get("tables_written", []):
                writers[t].add(i)
    return {t: sorted(s) for t, s in writers.items()}


def _chatty_pair(part: Partition, share: float) -> tuple[int, int, float] | None:
    best: tuple[int, int, float] | None = None
    ext = [part.external(i) for i in range(len(part.groups))]
    for i in range(len(part.groups)):
        for j in range(i + 1, len(part.groups)):
            inter = part.weight(part.groups[i], part.groups[j])
            if inter <= 0 or ext[i] <= 0 or ext[j] <= 0:
                continue
            both = min(inter / ext[i], inter / ext[j])
            if both >= share and (best is None or both > best[2]):
                best = (i, j, both)
    return best


def apply_rules(part: Partition, options: Options) -> None:
    """Merge until no rule fires (each merge is recorded in `part.log` with its reason)."""
    for _ in range(40):
        owners = table_owners(part)
        shared = next(((t, g) for t, g in sorted(owners.items()) if len(g) > 1), None)
        if shared:
            table, g = shared
            part.merge(g[0], g[1], f"both write the table `{table}` (one owner per table, strong consistency)")
            continue
        cycles = sync_cycles(part.group_edges(), len(part.groups))
        if cycles:
            c = cycles[0]
            part.merge(c[0], c[1], "they call each other (no synchronous cycles between services)")
            continue
        chatty = _chatty_pair(part, options.chatty_share)
        if chatty:
            part.merge(chatty[0], chatty[1], f"{round(chatty[2] * 100)}% of their traffic is with each other (chatty)")
            continue
        nano = next(
            (
                i
                for i, g in enumerate(part.groups)
                if part.files(g) < options.min_files and part.symbols(g) < options.min_symbols and part.external(i) > 0
            ),
            None,
        )
        if nano is not None:
            partner = max(
                (j for j in range(len(part.groups)) if j != nano),
                key=lambda j: (part.weight(part.groups[nano], part.groups[j]), -j),
            )
            part.merge(nano, partner, "too small to stand alone (no nano-services)")
            continue
        return


# ── scores and violations ────────────────────────────────────────────────────
def modularity(part: Partition) -> float:
    m2 = 2 * sum(part.pair_w.values())
    if m2 == 0:
        return 0.0
    q = 0.0
    for g in part.groups:
        inside = 2 * part.internal(g)
        degree = sum(part.pair_w.get(key(x, y), 0.0) for x in g for y in part.nodes if y != x)
        q += inside / m2 - (degree / m2) ** 2
    return q


def design_score(part: Partition, options: Options) -> dict[str, Any]:
    q = modularity(part)
    files = [part.files(g) for g in part.groups]
    balance = 1 - (max(files) / sum(files)) if files and sum(files) and len(files) > 1 else 0.0
    n = len(part.groups)
    size_fit = max(0.0, 1 - abs(n - options.ideal_groups) / 10)
    score = round(100 * (0.6 * min(1.0, max(0.0, q) / 0.35) + 0.25 * balance + 0.15 * size_fit))
    return {"score": score, "modularity": round(q, 3), "balance": round(balance, 2), "group_count": n}


def violations(part: Partition, options: Options) -> list[dict[str, Any]]:
    """Rules the design breaks as it stands (after the engine, only what a user's edit can introduce)."""
    out: list[dict[str, Any]] = []
    names = [", ".join(_labels(g)) for g in part.groups]
    for c in sync_cycles(part.group_edges(), len(part.groups)):
        out.append(
            {
                "rule": "no_sync_cycles",
                "groups": [names[i] for i in c],
                "message": f"{' ⇄ '.join(names[i] for i in c)} call each other.",
            }
        )
    for t, g in table_owners(part).items():
        if len(g) > 1:
            out.append(
                {
                    "rule": "one_owner_per_table",
                    "groups": [names[i] for i in g],
                    "message": f"The table `{t}` is written by {' and '.join(names[i] for i in g)}.",
                }
            )
    chatty = _chatty_pair(part, options.chatty_share)
    if chatty:
        out.append(
            {
                "rule": "chatty_pairs",
                "groups": [names[chatty[0]], names[chatty[1]]],
                "message": f"{names[chatty[0]]} and {names[chatty[1]]} mostly talk to each other.",
            }
        )
    for i, grp in enumerate(part.groups):
        if (
            part.files(grp) < options.min_files
            and part.symbols(grp) < options.min_symbols
            and not _is_frontend_group(part, grp)
        ):
            out.append(
                {
                    "rule": "no_nano_services",
                    "groups": [names[i]],
                    "message": f"{names[i]} is very small ({part.files(grp)} file(s)).",
                }
            )
    if options.one_frontend and sum(_is_frontend_group(part, g) for g in part.groups) > 1:
        out.append({"rule": "one_frontend", "groups": [], "message": "There is more than one frontend."})
    return out


def _is_frontend_group(part: Partition, g: list[str]) -> bool:
    return all(is_frontend(part.nodes[m]) for m in g)


# ── designs ──────────────────────────────────────────────────────────────────
def name_groups(groups: list[list[str]], nodes: dict[str, dict[str, Any]], pair_w: dict[Pair, float]) -> list[str]:
    """Readable, unique names: the module itself, else its most connected member, else the shared folder."""
    names: list[str] = []
    for g in groups:
        if g and all(is_frontend(nodes[m]) for m in g):
            base = FRONTEND
        elif len(g) == 1:
            base = nodes[g[0]].get("label") or g[0].rsplit("/", 1)[-1]
        else:
            hub = max(g, key=lambda m: (sum(pair_w.get(key(m, o), 0.0) for o in g if o != m), m))
            base = hub.rsplit("/", 1)[-1]
        name, n = base, 2
        while name in names:
            name, n = f"{base}-{n}", n + 1
        names.append(name)
    return names


def make_design(  # noqa: PLR0913  (a partition and how it was made)
    graph: dict[str, Any], groups: list[list[str]], pair_w: dict[Pair, float], options: Options, *,
    frontend: list[str] | None = None, log: list[str] | None = None, resolution: float | None = None, edited: bool = False,  # noqa: E501
    keep_names: dict[tuple[str, ...], str] | None = None,
) -> dict[str, Any]:  # fmt: skip
    """A design from a partition (the backend groups, plus the one frontend if there is one)."""
    all_groups = [g for g in groups if g] + ([sorted(frontend)] if frontend else [])
    part = Partition(graph, all_groups, pair_w)
    names = name_groups(part.groups, part.nodes, pair_w)
    names = [(keep_names or {}).get(tuple(sorted(g)), n) for g, n in zip(part.groups, names, strict=True)]
    edges = part.group_edges()
    scored = design_score(
        Partition(graph, [g for g in part.groups if not _is_frontend_group(part, g)], pair_w), options
    )
    items = []
    for i, g in enumerate(part.groups):
        fe = _is_frontend_group(part, g)
        items.append(
            {
                "name": names[i],
                "kind": "frontend" if fe else "backend",
                "modules": g,
                "files": part.files(g),
                "symbols": part.symbols(g),
                "internal": round(part.internal(g), 2),
                "external": round(part.external(i), 2),
                "calls": sorted({names[b] for (a, b) in edges if a == i}),
                "called_by": sorted({names[a] for (a, b) in edges if b == i}),
                "tables": sorted({t for m in g for t in part.nodes[m].get("tables_written", [])}),
            }
        )
    return {
        "groups": items,
        "resolution": resolution,
        "options": asdict(options),
        **scored,
        "rules_applied": list(log or []),
        "violations": violations(part, options),
        "edited": edited,
    }


def decompose(
    graph: dict[str, Any],
    *,
    weights: Weights = DEFAULT_WEIGHTS,
    options: Options = DEFAULT_OPTIONS,
    resolution: float = 1.0,
) -> dict[str, Any]:
    pair_w = pair_weights(graph, weights)
    nodes = [n["id"] for n in graph["nodes"]]
    front = [n["id"] for n in graph["nodes"] if options.one_frontend and is_frontend(n)]
    back = [n for n in nodes if n not in front]
    part = Partition(graph, louvain(back, pair_w, resolution), pair_w)
    apply_rules(part, options)
    return make_design(graph, part.groups, pair_w, options, frontend=front, log=part.log, resolution=resolution)


def alternatives(
    graph: dict[str, Any], *, weights: Weights = DEFAULT_WEIGHTS, options: Options = DEFAULT_OPTIONS
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The best design and the others considered (distinct partitions at several resolutions), each with why not."""
    seen: dict[tuple[tuple[str, ...], ...], dict[str, Any]] = {}
    for r in RESOLUTIONS:
        d = decompose(graph, weights=weights, options=options, resolution=r)
        seen.setdefault(tuple(sorted(tuple(g["modules"]) for g in d["groups"])), d)
    ranked = sorted(seen.values(), key=lambda d: (-d["score"], abs(_backend(d) - options.ideal_groups)))
    best = ranked[0]
    others = []
    for d in ranked[1:]:
        n_best, n = _backend(best), _backend(d)
        why = f"{n} group(s) score {d['score']} against {best['score']}: " + (
            "more traffic would cross group boundaries" if n > n_best else "unrelated modules would share a group"
        )
        others.append({"groups": [g["modules"] for g in d["groups"]], "count": n, "score": d["score"], "why_not": why})
    return best, others


def _backend(design: dict[str, Any]) -> int:
    return sum(g["kind"] == "backend" for g in design["groups"])


def explain(design: dict[str, Any], others: list[dict[str, Any]] | None = None) -> list[str]:
    """ "Why N groups": one line per group and per rule that shaped the design."""
    n = _backend(design)
    lines = [
        f"{n} backend group(s) and {'one frontend' if len(design['groups']) > n else 'no frontend'}, "
        f"design score {design['score']}/100."
    ]
    for g in design["groups"]:
        if g["kind"] == "frontend":
            lines.append(f"**{g['name']}**: all UI modules stay together (one frontend).")
            continue
        parts = [f"**{g['name']}** ({', '.join(_labels(g['modules']))})"]
        if g["calls"]:
            parts.append(f"calls {', '.join(g['calls'])}")
        if g["tables"]:
            parts.append(f"owns {', '.join(g['tables'])}")
        lines.append(": ".join([parts[0], "; ".join(parts[1:]) or "stands alone"]))
    lines += [f"Merged {line}" for line in design["rules_applied"]]
    lines += [f"Alternative: {o['why_not']}" for o in (others or [])]
    return lines


# ── editing on the graph ─────────────────────────────────────────────────────
def edit_design(
    graph: dict[str, Any], design: dict[str, Any], edit: dict[str, Any], *, weights: Weights = DEFAULT_WEIGHTS
) -> dict[str, Any]:
    """Apply the user's edit and re-validate. Edits: `{"move": {"module", "to"}}`, `{"merge": [a, b]}`,
    `{"split": {"group", "modules", "name"}}`, `{"rename": {"from", "to"}}`. Raises ValueError for an edit that names
    something that isn't there. The rules are not applied again (the edit stands); what it breaks is in `violations`."""
    options = Options(**design["options"])
    groups = {g["name"]: list(g["modules"]) for g in design["groups"] if g["kind"] == "backend"}
    front = next((list(g["modules"]) for g in design["groups"] if g["kind"] == "frontend"), None)
    log = [*design["rules_applied"]]
    names = {m: g for g, ms in groups.items() for m in ms}

    def need(name: str) -> None:
        if name not in groups:
            raise ValueError(f"There is no group called {name!r}. Groups: {', '.join(groups)}.")

    if "move" in edit:
        module, to = edit["move"]["module"], edit["move"]["to"]
        if module not in names:
            raise ValueError(f"{module!r} is not a backend module of this design.")
        need(to)
        groups[names[module]].remove(module)
        groups[to].append(module)
        log.append(f"You moved {module} to {to}.")
    elif "merge" in edit:
        a, b = edit["merge"]
        need(a)
        need(b)
        groups[a] += groups.pop(b)
        log.append(f"You merged {b} into {a}.")
    elif "split" in edit:
        spec = edit["split"]
        need(spec["group"])
        moved = [m for m in spec["modules"] if m in groups[spec["group"]]]
        if not moved or len(moved) == len(groups[spec["group"]]):
            raise ValueError("A split needs some, but not all, of the group's modules.")
        groups[spec["group"]] = [m for m in groups[spec["group"]] if m not in moved]
        groups[spec.get("name") or f"{spec['group']}-2"] = moved
        log.append(f"You split {', '.join(moved)} out of {spec['group']}.")
    elif "rename" in edit:
        need(edit["rename"]["from"])
        groups[edit["rename"]["to"]] = groups.pop(edit["rename"]["from"])
        log.append(f"You renamed {edit['rename']['from']} to {edit['rename']['to']}.")
    else:
        raise ValueError("Unknown edit. Use move, merge, split or rename.")
    result = make_design(
        graph, [g for g in groups.values() if g], pair_weights(graph, weights), options,
        frontend=front, log=log, resolution=design.get("resolution"), edited=True,
        keep_names={tuple(sorted(ms)): n for n, ms in groups.items()},
    )  # fmt: skip
    return result


def relabel(design: dict[str, Any], names: dict[str, str], purposes: dict[str, str] | None = None) -> dict[str, Any]:
    """The design with some groups renamed (`names`: old → new) and optionally a `purpose` for each."""

    def swap(items: list[str]) -> list[str]:
        return [names.get(x, x) for x in items]

    out = {**design, "groups": [], "violations": []}
    for g in design["groups"]:
        new = {
            **g,
            "name": names.get(g["name"], g["name"]),
            "calls": swap(g["calls"]),
            "called_by": swap(g["called_by"]),
        }
        if purposes and g["name"] in purposes:
            new["purpose"] = purposes[g["name"]]
        out["groups"].append(new)
    out["violations"] = [{**v, "groups": swap(v["groups"])} for v in design["violations"]]
    return out


def parse_edits(text: str, design: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn what the user typed at the approval ("move payment to order", "merge user and product", "rename order to
    checkout", "split db out of product") into edits for `edit_design`. Names are matched against the design's group
    names and module names, ignoring case. A sentence that isn't an edit gives nothing."""
    groups = {g["name"].lower(): g["name"] for g in design["groups"] if g["kind"] == "backend"}
    modules: dict[str, str] = {}
    for g in design["groups"]:
        for m in g["modules"]:
            modules.setdefault(m.lower(), m)
            modules.setdefault(m.rsplit("/", 1)[-1].lower(), m)

    def group(word: str) -> str | None:
        return groups.get(word.strip("`'\".,").lower())

    def module(word: str) -> str | None:
        return modules.get(word.strip("`'\".,").lower())

    edits: list[dict[str, Any]] = []
    for sentence in re.split(r"[.;\n]", text):
        s = sentence.strip()
        if (
            (m := re.match(r"(?i)move\s+(\S+)\s+(?:to|into|in)\s+(\S+)", s))
            and (mod := module(m[1]))
            and (to := group(m[2]))
        ):
            edits.append({"move": {"module": mod, "to": to}})
        elif (
            (m := re.match(r"(?i)merge\s+(\S+)\s+(?:and|with|into)\s+(\S+)", s))
            and (a := group(m[1]))
            and (b := group(m[2]))
        ):
            edits.append({"merge": [b, a] if " into " in s.lower() else [a, b]})
        elif (m := re.match(r"(?i)rename\s+(\S+)\s+(?:to|as)\s+([\w-]+)", s)) and (a := group(m[1])):
            edits.append({"rename": {"from": a, "to": m[2].strip("`'\".,")}})
        elif (
            (m := re.match(r"(?i)split\s+(\S+)\s+(?:out of|from)\s+(\S+)", s))
            and (mod := module(m[1]))
            and (src := group(m[2]))
        ):
            edits.append({"split": {"group": src, "modules": [mod], "name": mod.rsplit("/", 1)[-1]}})
    return edits
