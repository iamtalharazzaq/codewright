"""The order services are built in, and which can be prepared at the same time (CODEWRIGHT.md 5.18 step 7).

Least coupled first: a service goes after every service it calls (so its callees already exist when its client is
written). Services that do not depend on each other form a **wave**; within a wave the work that touches only the
service's own folder (spec, scaffold) runs concurrently, up to `max_parallel`. What changes the monolith (the
extraction and its anti-corruption layer) is always one service at a time, because it is one working tree.
"""

from __future__ import annotations

from typing import Any


def waves(design: dict[str, Any], max_parallel: int = 2) -> list[list[str]]:
    """Waves of services, callees before callers, least coupled first; no wave is larger than `max_parallel`."""
    backend = {g["name"]: g for g in design["groups"] if g["kind"] == "backend"}
    left = dict(backend)
    done: set[str] = set()
    out: list[list[str]] = []
    while left:
        ready = sorted(
            (n for n, g in left.items() if all(c in done or c not in backend for c in g["calls"])),
            key=lambda n: (len(left[n]["calls"]) + len(left[n]["called_by"]), n),
        )
        if not ready:  # a cycle the rules should have removed: build the least coupled one alone
            ready = [min(left, key=lambda n: (len(left[n]["calls"]) + len(left[n]["called_by"]), n))]
        for i in range(0, len(ready), max(1, max_parallel)):
            out.append(ready[i : i + max(1, max_parallel)])
        done.update(ready)
        for n in ready:
            del left[n]
    return out


def order(design: dict[str, Any], max_parallel: int = 2) -> list[str]:
    return [n for wave in waves(design, max_parallel) for n in wave]


def wave_of(design: dict[str, Any], name: str, max_parallel: int = 2) -> list[str]:
    return next((w for w in waves(design, max_parallel) if name in w), [name])
