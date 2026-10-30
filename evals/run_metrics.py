"""Phase 20 metrics from the runs Codewright has already done: success per playbook, time per task, human
interventions (approval gates) and model use.

    python3 -m evals.run_metrics [--api http://localhost:8000/api] [--limit 500]

Retries are not recorded per run, so they are not reported here.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections import defaultdict
from datetime import datetime
from typing import Any


def get(api: str, path: str) -> Any:
    with urllib.request.urlopen(api + path, timeout=60) as r:  # noqa: S310  (the user's own API)
        return json.loads(r.read())


def _minutes(run: dict[str, Any]) -> float:
    start, end = (datetime.fromisoformat(run[k]) for k in ("created_at", "updated_at"))
    return (end - start).total_seconds() / 60


def summarize(runs: list[dict[str, Any]], details: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per playbook: how many runs finished, how many succeeded, and the average minutes, approvals and model calls
    of the completed ones. Cancelled runs are counted but are neither a success nor a failure."""
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by[run["playbook"]].append(run)
    out: dict[str, dict[str, Any]] = {}
    for playbook, items in sorted(by.items()):
        done = [r for r in items if r["status"] == "completed"]
        failed = [r for r in items if r["status"] == "failed"]
        extra = [details[r["id"]] for r in done if r["id"] in details]
        out[playbook] = {
            "runs": len(items),
            "completed": len(done),
            "failed": len(failed),
            "cancelled": sum(r["status"] == "cancelled" for r in items),
            "success": len(done) / (len(done) + len(failed)) if done or failed else None,
            "minutes": sum(_minutes(r) for r in done) / len(done) if done else None,
            "approvals": sum(len(d["approvals"]) for d in extra) / len(extra) if extra else None,
            "llm_calls": sum(d["usage"]["llm_calls"] for d in extra) / len(extra) if extra else None,
        }
    return out


def render(table: dict[str, dict[str, Any]]) -> str:
    def num(x: float | None, fmt: str) -> str:
        return "-" if x is None else format(x, fmt)

    lines = [
        f"{'playbook':<22}{'runs':>5}{'ok':>5}{'fail':>5}{'cancel':>7}{'success':>8}{'min':>7}{'asks':>6}{'calls':>7}"
    ]
    for name, m in table.items():
        success = "-" if m["success"] is None else f"{m['success']:.0%}"
        lines.append(
            f"{name:<22}{m['runs']:>5}{m['completed']:>5}{m['failed']:>5}{m['cancelled']:>7}{success:>8}"
            f"{num(m['minutes'], '.1f'):>7}{num(m['approvals'], '.1f'):>6}{num(m['llm_calls'], '.0f'):>7}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    runs = get(args.api, f"/runs?limit={args.limit}")
    details = {r["id"]: get(args.api, f"/runs/{r['id']}") for r in runs if r["status"] == "completed"}
    print(render(summarize(runs, details)))


if __name__ == "__main__":
    main()
