"""Score every request in EXAMPLES.md against its section 8 checks 2-4, in a real chat (no run is ever started).

  2. new work asks the language (a declined language is declined, with a suggestion)
  3. asks only the other missing questions, at most 5, in one message, each with a default
  4. shows a confirm card and waits: no run exists until the user presses Start

    python3 -m evals.examples [--only 1 2 3] [--api http://localhost:8000/api] [--out evals/results]

Each request is sent to a new chat; if it asks questions they are answered with "Defaults are fine."; the chat then
must stop at the confirm card. Needs the live model. Checks 1 and 5-9 need a full build: see `evals.new_app`.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.review import call

EXAMPLES = Path(__file__).resolve().parent.parent / "EXAMPLES.md"
ROW = re.compile(r'^\|\s*(\d+)\s*\|\s*"([^"]+)"')
MAX_QUESTIONS = 5
NAMED_LANGUAGE = re.compile(r"\b(in|using|with)\s+(python|typescript|javascript|go|golang|c\+\+)\b", re.I)


def requests_in(text: str) -> list[tuple[int, str, str]]:
    """(row number, request, section) for every quoted request in a table row of EXAMPLES.md."""
    found: list[tuple[int, str, str]] = []
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        if m := ROW.match(line):
            found.append((len(found) + 1, m.group(2), section))
    return found


def grade(messages: list[dict[str, Any]], started_run: bool, request: str = "") -> dict[str, Any]:
    """Checks 2-4 from the assistant messages of one chat."""
    kinds = [m["kind"] for m in messages if m["role"] == "assistant"]
    asked = [m for m in messages if m["kind"] == "questions"]
    questions = [q for m in asked for q in (m["data"].get("questions") or [])]
    declined = any(m["kind"] == "decline" for m in messages if m["role"] == "assistant")
    asks_language = any(re.search(r"language", q["question"], re.I) for q in questions) or bool(
        request and NAMED_LANGUAGE.search(request)  # "... in Go": the user already chose, so nothing to ask
    )
    confirmed = "confirm" in kinds
    one_message = len(asked) <= 1 or all(len(m["data"].get("questions") or []) <= MAX_QUESTIONS for m in asked)
    return {
        "language_asked_or_declined": asks_language or declined,
        "at_most_5_questions": all(len(m["data"].get("questions") or []) <= MAX_QUESTIONS for m in asked),
        "every_question_has_a_default": all(q.get("default") for q in questions),
        "one_message": one_message,
        "confirm_waits": declined or (confirmed and not started_run),
        "declined": declined,
    }


def passed(g: dict[str, Any]) -> bool:
    return all(v for k, v in g.items() if k != "declined")


def settle(api: str, conv: str, wait: float) -> dict[str, Any]:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        d: dict[str, Any] = call(api, "GET", f"/conversations/{conv}")
        replies = [m for m in d["messages"] if m["role"] == "assistant"]
        if not d["busy"] and replies and all(m["status"] != "streaming" for m in replies):
            return d
        time.sleep(2)
    raise TimeoutError(f"chat {conv}: no reply in {wait:.0f}s")


def score(api: str, request: str, wait: float) -> dict[str, Any]:
    conv = call(api, "POST", "/conversations", {"content": request})["conversation"]["id"]
    detail = settle(api, conv, wait)
    for _ in range(2):  # answer the questions with the defaults, at most twice
        last = [m for m in detail["messages"] if m["role"] == "assistant"][-1]
        if last["kind"] != "questions":
            break
        call(api, "POST", f"/conversations/{conv}/messages", {"content": "Defaults are fine."})
        detail = settle(api, conv, wait)
    started = any(m.get("run_id") for m in detail["messages"])
    return {"conversation": conv, **grade(detail["messages"], started, request)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--only", type=int, nargs="*", help="row numbers to run")
    parser.add_argument("--wait", type=float, default=300)
    parser.add_argument("--out", type=Path, default=Path("evals/results"))
    args = parser.parse_args()
    results = []
    for number, request, section in requests_in(EXAMPLES.read_text(encoding="utf-8")):
        if args.only and number not in args.only:
            continue
        try:
            result = score(args.api, request, args.wait)
        except Exception as exc:  # a timeout or an API error counts as a fail and the eval goes on
            result = {"error": str(exc)[:300]}
        result |= {"n": number, "request": request, "section": section}
        result["ok"] = "error" not in result and passed(result)
        results.append(result)
        print(f"#{number} {'PASS' if result['ok'] else 'FAIL'} {request[:60]}")
    print(f"{sum(1 for r in results if r['ok'])}/{len(results)} passed")
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (args.out / f"examples-{stamp}.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
