"""Intent Router accuracy on labeled messages (CODEWRIGHT.md Phase 2), including every request in EXAMPLES.md.

    uv run python -m evals.router --url https://<gpu>/v1 --out evals/results/

`decline` means an unsupported language (declined by rule); `off_topic` means a non-software decline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from agent.chat.router import route
from agent.llm.client import LLMClient
from agent.llm.config import LLMProfile

CASES = Path(__file__).parent / "data" / "router_cases.jsonl"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", default="Qwen3.5-9B-Q4_K_M.gguf")
    parser.add_argument("--profile", default="remote_gpu", choices=["local_cpu", "remote_gpu"])
    parser.add_argument("--out", type=Path, default=Path("evals/results"))
    args = parser.parse_args()
    client = LLMClient(
        args.profile, LLMProfile(base_url=args.url, model=args.model, num_ctx=4096, api_key_env="REMOTE_GPU_API_KEY")
    )
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]

    results: list[dict[str, object]] = []
    per_label: Counter[tuple[str, bool]] = Counter()
    wrong: list[str] = []
    start = time.monotonic()
    for case in cases:
        r = await route(client, case["text"])
        got = r.intent or ("decline" if r.decline and "supported" in r.decline else "off_topic")
        ok = got == case["intent"]
        per_label[(case["intent"], ok)] += 1
        results.append({**case, "got": got, "tier": r.tier, "confidence": r.confidence, "ok": ok, "asked": r.question})
        if not ok:
            wrong.append(f"  {case['text']!r}: expected {case['intent']}, got {got}")
    elapsed = time.monotonic() - start

    correct = sum(1 for x in results if x["ok"])
    print(
        f"Router accuracy: {correct}/{len(results)} = {correct / len(results):.0%} "
        f"({elapsed / len(results):.1f}s per message)"
    )
    labels = sorted({c["intent"] for c in cases})
    for label in labels:
        good, bad = per_label[(label, True)], per_label[(label, False)]
        print(f"  {label:22} {good}/{good + bad}")
    if wrong:
        print("Misses:\n" + "\n".join(wrong))
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (args.out / f"router-{stamp}.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
