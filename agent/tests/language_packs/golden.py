"""What each pack makes of the fixtures. `python -m agent.tests.language_packs.golden` rewrites `expected/*.json`
after an intended change; review the diff."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.language_packs import detect_project, pack
from agent.language_packs.executor import plan

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = Path(__file__).parent / "expected"


def snapshot(name: str) -> dict[str, Any]:
    repo = FIXTURES / name
    out: dict[str, Any] = {"components": []}
    for c in detect_project(repo):
        p = pack(c.pack)
        run = p.run_spec(repo, c)
        out["components"].append(
            {
                "component": c.as_dict(),
                "graph": p.parse(repo, c).as_dict(),
                "plans": {a: [s.as_dict() for s in plan(repo, c, a)] for a in ("build", "test", "lint")},
                "run": run.as_dict() if run else None,
            }
        )
    return out


def main() -> None:
    EXPECTED.mkdir(exist_ok=True)
    for fixture in sorted(p.name for p in FIXTURES.iterdir() if p.is_dir()):
        (EXPECTED / f"{fixture}.json").write_text(json.dumps(snapshot(fixture), indent=2) + "\n", encoding="utf-8")
        print("wrote", fixture)


if __name__ == "__main__":
    main()
