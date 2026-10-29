"""The Language Advisor (CODEWRIGHT.md Section 5.18 step 5, Section 5.16): a language for each service, with the reason.

Rule-based: the service's workload (from what its modules are called) is scored against the five supported
languages. **The default is to keep the original language**; a change is advised only when another language beats
the current one by a clear margin, which grows with the amount of code that would have to be rewritten. The mode
is `extract` (same language: move code) or `translate` (new language: spec first, function by function).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

SUPPORTED = ("Python", "TypeScript", "JavaScript", "Go", "C++")
WORKLOADS: dict[str, set[str]] = {
    "compute": {
        "pricing",
        "engine",
        "codec",
        "rank",
        "ranking",
        "solver",
        "compress",
        "crypto",
        "parser",
        "image",
        "video",
        "render",
        "simulation",
        "matching",
        "routing",
        "geometry",
    },
    "data": {
        "report",
        "reports",
        "analytics",
        "etl",
        "pipeline",
        "batch",
        "import",
        "export",
        "ml",
        "training",
        "stats",
        "forecast",
        "ingest",
    },
    "io": {
        "gateway",
        "notification",
        "notifications",
        "proxy",
        "webhook",
        "webhooks",
        "email",
        "sms",
        "sync",
        "client",
        "relay",
        "events",
        "stream",
        "chat",
        "websocket",
    },
}
FIT: dict[str, dict[str, int]] = {
    "crud": {"Python": 4, "TypeScript": 4, "JavaScript": 3, "Go": 4, "C++": 1},
    "io": {"Python": 3, "TypeScript": 4, "JavaScript": 3, "Go": 5, "C++": 2},
    "compute": {"Python": 2, "TypeScript": 2, "JavaScript": 1, "Go": 4, "C++": 5},
    "data": {"Python": 5, "TypeScript": 2, "JavaScript": 2, "Go": 3, "C++": 3},
}
WORKLOAD_TEXT = {
    "crud": "mostly business rules and database access",
    "io": "mostly waiting on the network (many connections, little computing)",
    "compute": "heavy computing",
    "data": "data processing",
}


def profile(modules: list[str], nodes: dict[str, dict[str, Any]], allowed: list[str] | None = None) -> dict[str, Any]:
    """What the advisor needs to know about a service: its main language, size and workload."""
    langs: Counter[str] = Counter()
    for m in modules:
        for lang, count in (nodes[m].get("languages") or {}).items():
            langs[lang] += count
    words = {w for m in modules for w in re.split(r"[^a-z0-9]+", m.lower()) if w}
    workload = next((w for w, vocab in WORKLOADS.items() if words & vocab), "crud")
    return {
        "current": langs.most_common(1)[0][0] if langs else None,
        "files": sum(nodes[m].get("file_count", 0) for m in modules),
        "workload": workload,
        "allowed": [x for x in (allowed or SUPPORTED) if x in SUPPORTED] or list(SUPPORTED),
    }


def advise(p: dict[str, Any]) -> dict[str, Any]:
    """`{"language", "mode", "current", "scores", "why"}` for one service profile."""
    table = FIT[p["workload"]]
    allowed = p["allowed"]
    current = p["current"] if p["current"] in SUPPORTED else None
    # Keeping what exists is worth more the more code there is; allowed languages only limit the alternatives.
    keep_bonus = 2 + min(2, p["files"] // 20)
    scores = {lang: table[lang] for lang in allowed}
    if current and current not in scores:
        scores[current] = table[current]
    ranked = sorted(scores, key=lambda lang: (-scores[lang], lang != current, SUPPORTED.index(lang)))
    best = ranked[0]
    why = [f"This service is {WORKLOAD_TEXT[p['workload']]}."]
    if current is None:
        language, mode = best, "translate"
        shown = p["current"] or "unknown"
        why.append(f"Its language ({shown}) is not one of the five supported ones, so {best} fits best.")
    elif best == current or table[best] - table[current] < keep_bonus + 1:
        language, mode = current, "extract"
        why.append(f"{current} stays: it is the original language and {best if best != current else 'no other language'} "  # noqa: E501
                   f"{'is not clearly better' if best != current else 'fits better'} "
                   f"(rewriting {p['files']} file(s) would cost more than it gains).")  # fmt: skip
        if current not in allowed:
            why.append(f"Note: {current} is not in the languages you allowed; it is kept because it is the original.")
    else:
        language, mode = best, "translate"
        why.append(f"{best} fits {table[best]}/5 against {table[current]}/5 for {current}, a gap of "
                   f"{table[best] - table[current]} (needs at least {keep_bonus + 1} to justify rewriting {p['files']} file(s)).")  # fmt: skip  # noqa: E501
    return {"language": language, "mode": mode, "current": current or p["current"], "scores": scores, "why": why}


def plan(design: dict[str, Any], nodes: dict[str, dict[str, Any]], allowed: list[str] | None = None) -> dict[str, Any]:
    """A language for each backend group of a design: `{group name: advice}`."""
    return {
        g["name"]: advise(profile(g["modules"], nodes, allowed)) for g in design["groups"] if g["kind"] == "backend"
    }
