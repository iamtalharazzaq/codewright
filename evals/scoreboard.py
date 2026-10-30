"""The Phase 20 scoreboard: the newest result file of each eval suite, as one table.

    python3 -m evals.scoreboard [--results evals/results]

Needs no model: it only reads what `evals.router`, `evals.write_code`, `evals.explain` and `evals.review` wrote.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

RESULTS = Path(__file__).parent / "results"


def latest(results: Path) -> dict[str, tuple[str, Any]]:
    """The newest file per suite (`router-2026….json` → suite `router`; `review-seeded-go-…` → `review-seeded-go`)."""
    found: dict[str, tuple[str, Any]] = {}
    for path in sorted(results.glob("*.json")):  # the stamp sorts by time, so the last one wins
        suite = path.stem.rsplit("-", 2)[0]
        found[suite] = (path.name, json.loads(path.read_text(encoding="utf-8")))
    return found


def _seconds(rows: list[dict[str, Any]]) -> float | None:
    times = [float(r["seconds"]) for r in rows if r.get("seconds")]
    return round(sum(times) / len(times), 1) if times else None


def score(suite: str, data: Any) -> dict[str, Any]:
    """{passed, total, seconds, by} for one suite's result file."""
    if suite == "router":
        return {"passed": sum(bool(r["ok"]) for r in data), "total": len(data), "seconds": None, "by": "intent"}
    if suite == "write_code":
        return {"passed": sum(bool(r["passed"]) for r in data), "total": len(data), "seconds": _seconds(data),
                "by": "language", "languages": _by_language(data)}  # fmt: skip
    if suite.startswith("explain"):
        return {
            "passed": sum(bool(r["ok"]) for r in data),
            "total": len(data),
            "seconds": _seconds(data),
            "by": "question",
        }
    if suite.startswith("review"):
        found = sum(bool(i["found"]) for i in data["issues"])
        return {"passed": found, "total": len(data["issues"]), "seconds": data.get("seconds") or None,
                "by": "seeded issue", "false_alarms": len(data["false_alarms"])}  # fmt: skip
    return {"passed": 0, "total": 0, "seconds": None, "by": "unknown suite"}


def _by_language(rows: list[dict[str, Any]]) -> dict[str, str]:
    totals: dict[str, list[int]] = {}
    for r in rows:
        passed_total = totals.setdefault(r.get("language") or "?", [0, 0])
        passed_total[0] += bool(r["passed"])
        passed_total[1] += 1
    return {lang: f"{p}/{t}" for lang, (p, t) in sorted(totals.items())}


def render(results: Path) -> str:
    rows = [(suite, name, score(suite, data)) for suite, (name, data) in sorted(latest(results).items())]
    if not rows:
        return "No eval results yet. Run `python3 -m evals.router` (or write_code, explain, review) first."
    lines = [f"{'suite':<22}{'passed':>10}{'rate':>7}{'avg s':>8}  file"]
    for suite, name, s in rows:
        rate = f"{s['passed'] / s['total']:.0%}" if s["total"] else "-"
        seconds = "-" if s["seconds"] is None else f"{s['seconds']}"
        extra = f"  ({s['false_alarms']} false alarm(s))" if s.get("false_alarms") else ""
        lines.append(f"{suite:<22}{s['passed']:>5}/{s['total']:<4}{rate:>7}{seconds:>8}  {name}{extra}")
        if s.get("languages"):
            lines.append(f"{'':<22}by language: " + ", ".join(f"{k} {v}" for k, v in s["languages"].items()))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=RESULTS)
    print(render(parser.parse_args().results))


if __name__ == "__main__":
    main()
