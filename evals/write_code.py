"""Write code eval (CODEWRIGHT.md Phase 8 acceptance): the 20 `EXAMPLES.md` section 2 requests, one `write_code` run
each (the language the table recommends or the request names), approved at the result gate. A run passes when its
tests pass in the sandbox (the verify step says "N test(s) passed"); a run that gives up says so and counts as a fail.

    python3 -m evals.write_code [--only 1 2 3] [--api http://localhost:8000/api] [--out evals/results]

Runs one after another (Codewright allows one active run). Standard library only; needs a running stack with the
sandbox images built.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.review import call, wait

EXAMPLES: list[tuple[int, str, str]] = [
    (1, "Write code to reverse a linked list (iterative)", "Python"),
    (2, "Check if a string is a palindrome (ignore case, spaces and punctuation; empty string is true)", "Python"),
    (3, "FizzBuzz from 1 to 100", "Python"),
    (4, "Binary search in a sorted array (not found, first and last element, duplicates)", "Python"),
    (5, "Two Sum: indices of two numbers adding to a target, O(n) with a hash map (no solution, negatives)", "Python"),
    (6, "Merge two sorted linked lists (one or both empty)", "Python"),
    (7, "Detect a cycle in a linked list with Floyd's algorithm (no cycle, cycle at head)", "Python"),
    (8, "Check balanced parentheses (mixed brackets, empty, unmatched)", "Python"),
    (9, "Implement an LRU cache with O(1) get and put (capacity 1, eviction order)", "Python"),
    (10, "Merge sort and quick sort (empty, duplicates, already sorted)", "C++"),
    (11, "Fibonacci with memoization (n = 0, 1, large n)", "Python"),
    (12, "Group anagrams (empty strings, single word)", "Python"),
    (13, "BFS and DFS on a graph (disconnected graph, cycles)", "Python"),
    (14, "Implement a stack and a queue (empty pop, peek)", "C++"),
    (15, "Implement a Trie with insert, search and startsWith (prefix vs full word)", "TypeScript"),
    (16, "Dijkstra's shortest path (unreachable nodes, ties)", "C++"),
    (17, "Rotate a matrix 90 degrees (1x1, n x n)", "Go"),
    (18, "Debounce function (rapid calls, trailing call, cancel)", "JavaScript"),
    (19, "Reverse a linked list in Go", "Go"),
    (20, "Matrix multiplication, as fast as possible (non-square, mismatched sizes)", "C++"),
]


def run_one(api: str, request: str, language: str, seconds: float) -> dict[str, Any]:
    run = call(api, "POST", "/runs", {"playbook": "write_code", "inputs": {"request": request, "language": language}})
    rid = str(run["id"])

    def finished() -> dict[str, Any] | None:
        now: dict[str, Any] = call(api, "GET", f"/runs/{rid}")
        if now["status"] in ("failed", "cancelled"):
            return now
        if now["status"] == "waiting" and now["pending"]:
            if now["pending"].get("kind") != "gate":
                return now  # a budget or model prompt: report it, don't answer for the user
            call(api, "POST", f"/runs/{rid}/answer", {"decision": "approve"})
            return None
        return now if now["status"] == "completed" else None

    final = wait(f"run {rid}", finished, seconds, every=5)
    verify = (final.get("steps") or {}).get("verify", {}).get("summary", "")
    passed = final["status"] == "completed" and "test(s) passed" in verify
    return {"run": rid, "status": final["status"], "passed": passed, "verify": verify, "error": final.get("error")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--only", type=int, nargs="*", help="example numbers to run")
    parser.add_argument("--wait", type=float, default=900, help="seconds per example")
    parser.add_argument("--out", type=Path, default=Path("evals/results"))
    args = parser.parse_args()
    results = []
    for number, request, language in EXAMPLES:
        if args.only and number not in args.only:
            continue
        started = time.monotonic()
        try:
            result = run_one(args.api, request, language, args.wait)
        except Exception as exc:  # a timeout or an API error counts as a fail and the eval goes on
            result = {"passed": False, "status": "error", "error": str(exc)[:300]}
        result |= {"n": number, "request": request, "language": language, "seconds": round(time.monotonic() - started)}
        results.append(result)
        verdict = "PASS" if result["passed"] else "FAIL"
        print(f"#{number} {language}: {verdict} {result.get('verify') or result.get('error')}")
    passed = sum(1 for r in results if r["passed"])
    print(f"{passed}/{len(results)} passed")
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (args.out / f"write_code-{stamp}.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
