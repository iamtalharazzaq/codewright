"""What a service design needs besides its services (CODEWRIGHT.md 5.18 step 4): the gateway routes, the events that
decouple fan-out, and the sagas for work that spans several services. Derived from the design's calls with simple
rules; the user reviews and edits the design, so these are proposals with their reasons, not facts.
"""

from __future__ import annotations

from typing import Any


def platform_design(design: dict[str, Any]) -> dict[str, Any]:
    groups = {g["name"]: g for g in design["groups"]}
    backend = {n: g for n, g in groups.items() if g["kind"] == "backend"}
    frontend = next((g for g in groups.values() if g["kind"] == "frontend"), None)
    # A fan-out service is called by several others and calls nothing itself (notifications, search, audit).
    fan_out = sorted(n for n, g in backend.items() if len(g["called_by"]) >= 2 and not g["calls"])
    events = [
        {
            "event": f"{name}.changed",
            "producer": name,
            "consumers": [f for f in fan_out if f in g["calls"]],
            "why": f"{name} no longer waits for {', '.join(f for f in fan_out if f in g['calls'])}.",
        }
        for name, g in sorted(backend.items())
        if any(f in g["calls"] for f in fan_out)
    ]
    sagas = []
    for name, g in sorted(backend.items()):
        steps = [c for c in g["calls"] if c in backend and c not in fan_out]
        if len(steps) >= 2:  # one business action that changes several services needs a way to undo
            ordered = sorted(steps, key=lambda c: (len(backend[c]["calls"]), c))
            sagas.append(
                {
                    "name": f"{name} workflow",
                    "orchestrator": name,
                    "steps": ordered,
                    "compensations": [f"undo {s}" for s in reversed(ordered)],
                    "why": f"{name} changes {', '.join(ordered)} in one action; if a later step fails the earlier ones are undone.",  # noqa: E501
                }
            )
    return {
        "gateway": {
            "routes": sorted(frontend["calls"])
            if frontend
            else sorted(n for n, g in backend.items() if not g["called_by"])
        },
        "broker": "NATS" if events else None,
        "auth": "JWT checked at the gateway",
        "events": events,
        "sagas": sagas,
    }
