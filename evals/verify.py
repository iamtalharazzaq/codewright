"""Verification eval (CODEWRIGHT.md Phase 7 acceptance): a fixture is imported as a ZIP, then Codewright writes
journeys (if none are given), records its traffic on a fresh app and self-replays the recording on another fresh
app. The acceptance is 0 regressions — the same requests meet the same behavior from a clean state.

    python3 evals/verify.py evals/data/verify/notes-api-python.json [--api http://localhost:8000/api] [--out ...]

Standard library only, so it runs anywhere; needs a running stack (`make up`) with the sandbox images built.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.review import call, import_zip, wait  # reuse the same ZIP-import and polling helpers

ROOT = Path(__file__).resolve().parent.parent


def start(api: str, project: str, action: str, options: dict[str, Any]) -> str:
    return str(call(api, "POST", f"/projects/{project}/verification/actions", {"action": action, **options})["id"])


def finished(api: str, project: str, activity_id: str, seconds: float) -> dict[str, Any]:
    def done() -> dict[str, Any] | None:
        status = call(api, "GET", f"/projects/{project}/verification")
        activity = next(a for a in status["activities"] if a["id"] == activity_id)
        return activity if activity["status"] != "running" else None

    result = wait("verification", done, seconds, every=5)
    if result["status"] == "error":
        raise RuntimeError(f"activity {activity_id} errored: {result.get('error')}")
    return dict(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case", type=Path, help="evals/data/verify/<fixture>.json")
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--project", help="an already imported copy of the fixture (skips the import)")
    parser.add_argument("--wait", type=float, default=900)
    parser.add_argument("--out", type=Path, default=Path("evals/results"))
    args = parser.parse_args()
    spec = json.loads(args.case.read_text(encoding="utf-8"))

    if not args.project and "repo" not in spec:
        parser.error(f'{args.case} has no "repo" (a third-party fixture): pass --project <an imported copy\'s id>')
    start_t = time.monotonic()
    if args.project:
        project = args.project
    else:
        repo = ROOT / spec["repo"]
        project = import_zip(args.api, repo, f"{repo.name}-{datetime.now(UTC):%H%M%S}")
    activity = finished(args.api, project, start(args.api, project, "record", {"self_check": True}), args.wait)
    report_id = next(r["id"] for r in activity["results"] if r["kind"] == "replay")
    report = call(args.api, "GET", f"/projects/{project}/verification/reports/{report_id}")
    counts = report["counts"]
    seconds = round(time.monotonic() - start_t)

    ok = counts["regression"] == 0
    print(
        f"{args.case.stem}: {counts['exchanges']} exchanges replayed, {counts['regression']} regression(s), "
        f"{counts['noise']} noise, {counts['identical']} identical; {'PASS' if ok else 'FAIL'}; {seconds}s; "
        f"project {project}"
    )
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = {"case": args.case.stem, "project": project, "report": report_id, "seconds": seconds, "ok": ok, **counts}
    (args.out / f"verify-{args.case.stem}-{stamp}.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
