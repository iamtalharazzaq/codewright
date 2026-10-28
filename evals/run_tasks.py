"""The eval harness skeleton (CODEWRIGHT.md Phase 7 task 5): one registry of tasks per playbook
(`evals/tasks/registry.json`), each naming a case file under `evals/data/` and the eval script that runs it
(`evals/explain.py`, `evals/review.py`, `evals/verify.py`, …). Running it goes through every task on its fixture
and reports pass/fail per task, so a playbook's evals grow by adding a case file and a registry entry, not a new
runner.

    python3 evals/run_tasks.py [--playbook explain] [--api http://localhost:8000/api] [--project <id> ...]

A task marked "needs_project" (its fixture isn't checked in, such as GoShop) is skipped unless `--project
<fixture-stem>=<id>` names an already-imported copy; pass it as many times as there are such tasks. Needs a
running stack (`make up`), and for `verify` tasks, the sandbox images.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "evals" / "tasks" / "registry.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--playbook", help="run only this playbook's tasks")
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument(
        "--project", action="append", default=[], metavar="FIXTURE=ID",
        help="an imported copy of a 'needs_project' fixture (its case file's stem=the project id); repeatable",
    )  # fmt: skip
    parser.add_argument("--out", type=Path, default=Path("evals/results"))
    args = parser.parse_args()
    projects = dict(p.split("=", 1) for p in args.project)
    tasks = json.loads(args.registry.read_text(encoding="utf-8"))
    if args.playbook:
        tasks = [t for t in tasks if t["playbook"] == args.playbook]

    results: list[dict[str, object]] = []
    for task in tasks:
        fixture = Path(task["args"][-1]).stem
        label = f"{task['playbook']}/{fixture}"
        if task.get("needs_project") and fixture not in projects:
            print(f"SKIP  {label} (needs_project: pass --project {fixture}=<id>)")
            results.append({"task": label, "status": "skipped"})
            continue
        cmd = [sys.executable, task["script"], *task["args"], "--api", args.api, "--out", str(args.out)]
        if fixture in projects:
            cmd += ["--project", projects[fixture]]
        print(f"RUN   {label}: {' '.join(cmd[1:])}")
        start = time.monotonic()
        proc = subprocess.run(cmd, cwd=ROOT, check=False)  # noqa: S603  (the repo's own eval scripts)
        seconds = round(time.monotonic() - start)
        status = "passed" if proc.returncode == 0 else "failed"
        print(f"{status.upper():6}{label} ({seconds}s)")
        results.append({"task": label, "status": status, "seconds": seconds})

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (args.out / f"tasks-{stamp}.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    passed = sum(r["status"] == "passed" for r in results)
    ran = sum(r["status"] != "skipped" for r in results)
    print(f"\n{passed}/{ran} task(s) passed ({sum(r['status'] == 'skipped' for r in results)} skipped)")
    if passed < ran:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
