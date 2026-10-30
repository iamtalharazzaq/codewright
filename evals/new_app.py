"""New-app eval (CODEWRIGHT.md Phase 20): small `EXAMPLES.md` section 3 apps built end to end, with acceptance checks.

A case passes when the run completed, its tests passed, the app's own source (test files left out) matches every `must`
pattern, and holds no test code (a browser cannot load `vitest`). `behavior` patterns are reported, not required.

    python3 -m evals.new_app [--only calculator-react] [--api http://localhost:8000/api] [--container codewright-api-1]

Runs one after another against a running stack and the live model; reads the built source from the API container.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.review import call, wait

CASES = Path(__file__).parent / "data" / "new_app_cases.json"
TEST_FILE = re.compile(r"(\.(test|spec)\.[jt]sx?$|(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.(go|py)$)")
TEST_CODE = re.compile(r"""from\s+['"](vitest|jest)['"]|^\s*(import pytest|def test_)|\bdescribe\(""", re.MULTILINE)
SOURCE_SUFFIX = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".cpp", ".h", ".html", ".css"}


def source_of(files: dict[str, str]) -> dict[str, str]:
    """The app's own source: no test files, no config, nothing under node_modules."""
    return {
        name: text
        for name, text in files.items()
        if TEST_FILE.search(name) is None
        and Path(name).suffix in SOURCE_SUFFIX
        and "node_modules" not in name
        and not Path(name).name.startswith(("vite.config", "vitest.config"))
    }


def grade(case: dict[str, Any], files: dict[str, str], tests_passed: bool) -> dict[str, Any]:
    """Acceptance for one built app: the required patterns, the optional behavior patterns, test code in source."""
    source = source_of(files)
    text = "\n".join(source.values())
    missing = [p for p in case["must"] if not re.search(p, text, re.I)]
    behavior = [p for p in case.get("behavior", []) if not re.search(p, text, re.I)]
    misplaced = sorted(name for name, body in source.items() if TEST_CODE.search(body))
    return {
        "missing": missing,
        "behavior_missing": behavior,
        "tests_in_source": misplaced,
        "tests_passed": tests_passed,
        "ok": tests_passed and not missing and not misplaced and bool(source),
    }


def read_files(container: str, project: str, limit: int = 200_000) -> dict[str, str]:
    """The built project's text files (the workspace lives in the API container)."""
    script = (
        f"cd /app/workspaces/{project}/work && git ls-files | grep -v -E '^(graphify-out|.codewright)/' | head -200 | "
        'while read f; do printf \'\\n=====FILE %s\\n\' "$f"; head -c 20000 "$f" 2>/dev/null; done'
    )
    out = subprocess.run(  # noqa: S603  (the user's own container)
        ["docker", "--context", "default", "exec", container, "sh", "-c", script],  # noqa: S607
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout[:limit]  # fmt: skip
    files: dict[str, str] = {}
    for chunk in out.split("\n=====FILE ")[1:]:
        name, _, body = chunk.partition("\n")
        files[name.strip()] = body
    return files


def run_case(api: str, container: str, case: dict[str, Any], seconds: float) -> dict[str, Any]:
    answers = [["Which language?", case["language"]]]
    if case.get("platform"):
        answers.append(["Which platform?", case["platform"]])
    inputs = {"request": case["request"], "language": case["language"], "size": "small", "answers": answers}
    run = call(api, "POST", "/runs", {"playbook": "new_app", "inputs": inputs})
    rid = str(run["id"])

    def finished() -> dict[str, Any] | None:
        now: dict[str, Any] = call(api, "GET", f"/runs/{rid}")
        if now["status"] in ("failed", "cancelled"):
            return now
        if now["status"] == "waiting" and now["pending"]:
            if now["pending"].get("kind") != "gate":
                return now
            call(api, "POST", f"/runs/{rid}/answer", {"decision": "approve"})
            return None
        return now if now["status"] == "completed" else None

    final = wait(f"run {rid}", finished, seconds, every=5)
    verify = (final.get("steps") or {}).get("verify", {})
    passed = final["status"] == "completed" and "test(s) passed" in str(verify.get("summary", ""))
    result: dict[str, Any] = {
        "run": rid,
        "status": final["status"],
        "verify": verify.get("summary"),
        "retries": final.get("retries", 0),
    }
    if final["status"] == "completed" and final.get("project_id"):
        result |= grade(case, read_files(container, str(final["project_id"])), passed)
    else:
        result |= {"ok": False, "error": final.get("error")}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--container", default="codewright-api-1")
    parser.add_argument("--only", nargs="*", help="case ids to run")
    parser.add_argument("--wait", type=float, default=1200, help="seconds per case")
    parser.add_argument("--out", type=Path, default=Path("evals/results"))
    args = parser.parse_args()
    results = []
    for case in json.loads(CASES.read_text(encoding="utf-8")):
        if args.only and case["id"] not in args.only:
            continue
        started = time.monotonic()
        try:
            result = run_case(args.api, args.container, case, args.wait)
        except Exception as exc:  # a timeout or an API error counts as a fail and the eval goes on
            result = {"ok": False, "error": str(exc)[:300]}
        result |= {"id": case["id"], "request": case["request"], "language": case["language"],
                   "seconds": round(time.monotonic() - started)}  # fmt: skip
        results.append(result)
        print(
            f"{case['id']}: {'PASS' if result['ok'] else 'FAIL'} {result.get('missing') or result.get('error') or ''}"
        )
    print(f"{sum(1 for r in results if r['ok'])}/{len(results)} passed")
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (args.out / f"new_app-{stamp}.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
