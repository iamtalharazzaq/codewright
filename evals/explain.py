"""Explain eval (CODEWRIGHT.md Phase 6 acceptance): questions about one project's code, asked end to end through the
chat API of a running stack, graded against facts checked in that project's source. One case file per project in
`evals/data/explain/` (GoShop is the first); add a file to evaluate another codebase.

    python3 evals/explain.py --cases evals/data/explain/goshop.jsonl --project <its project id> [--api ...] [--out ...]

A question passes when every fact (a case-insensitive regex) is in the answer and, when given, the answer names the
file the code lives in. Answers that hedge with "likely" are counted too. Standard library only, so it runs anywhere.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CASES = Path(__file__).parent / "data" / "explain" / "goshop.jsonl"


def call(api: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(  # noqa: S310  (the user's own API)
        api + path, method=method, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310  (the user's own API)
        text = r.read()
        return json.loads(text) if text else None


def ask(api: str, project: str, question: str, wait: float) -> dict[str, Any]:
    """A new project chat with one question → the finished reply."""
    conv = call(api, "POST", "/conversations", {"content": question, "project_id": project})["conversation"]["id"]
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        d = call(api, "GET", f"/conversations/{conv}")
        replies = [m for m in d["messages"] if m["role"] == "assistant"]
        if not d["busy"] and replies and all(m["status"] != "streaming" for m in replies):
            return {"conversation": conv, **replies[-1]}
        time.sleep(2)
    raise TimeoutError(f"no answer to {question!r} in {wait:.0f}s")


def grade(case: dict[str, Any], answer: str) -> dict[str, Any]:
    missing = [f for f in case["facts"] if not re.search(f, answer, re.I)]
    cites = not case.get("file") or case["file"] in answer
    return {"missing": missing, "cites_file": cites, "hedges": len(re.findall(r"\blikely\b", answer, re.I))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True)
    parser.add_argument("--cases", type=Path, default=CASES, help="a JSONL file: id, question, facts, file")
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--wait", type=float, default=300)
    parser.add_argument("--out", type=Path, default=Path("evals/results"))
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.only:
        cases = [c for c in cases if c["id"] in args.only.split(",")]

    results: list[dict[str, Any]] = []
    for case in cases:
        start = time.monotonic()
        reply = ask(args.api, args.project, case["question"], args.wait)
        g = grade(case, reply["content"])
        ok = not g["missing"] and g["cites_file"]
        diagram = bool((reply.get("data") or {}).get("diagram"))
        results.append(
            {**case, **g, "ok": ok, "seconds": round(time.monotonic() - start, 1), "diagram": diagram,
             "conversation": reply["conversation"], "answer": reply["content"]}
        )  # fmt: skip
        mark = "PASS" if ok else "FAIL"
        extra = (f" missing {g['missing']}" if g["missing"] else "") + ("" if g["cites_file"] else " (file not named)")
        print(f"{mark} {case['id']:16} {results[-1]['seconds']:5.1f}s diagram={'yes' if diagram else 'no '}{extra}")

    passed = sum(r["ok"] for r in results)
    hedged = sum(1 for r in results if r["hedges"])
    print(f"Explain on {args.cases.stem}: {passed}/{len(results)} correct; {hedged} answer(s) say 'likely'")
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = args.out / f"explain-{args.cases.stem}-{stamp}.json"
    out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
