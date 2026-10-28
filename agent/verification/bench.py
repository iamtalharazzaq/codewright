"""Benchmarks with k6 (CODEWRIGHT.md Phase 7 task 4): load on the read requests of a recording, per-endpoint latency,
and a comparison with an earlier run of the same recording (before/after a change).

The requests come from a replay on a fresh app, so IDs and tokens are this run's. Only GETs that succeeded are
used: a benchmark must not create or delete data, and the numbers mean nothing for requests that fail.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from agent.verification.traffic import Request

MAX_TARGETS = 20
SAFE_HEADERS = {"authorization", "accept", "accept-language", "x-api-key", "content-type"}


@dataclass
class Target:
    name: str  # METHOD /path/{id}: the endpoint, so numbers group per endpoint
    method: str
    path: str
    headers: dict[str, str]


def endpoint_name(method: str, path: str) -> str:
    """`GET /api/products/3f2c…?page=2` → `GET /api/products/{id}`: IDs and numbers become a placeholder."""
    parts = [
        "{id}" if re.fullmatch(r"\d+|[0-9a-fA-F-]{16,}|[A-Za-z0-9_-]{20,}", p) else p
        for p in urlsplit(path).path.split("/")
    ]
    return f"{method} {'/'.join(parts)}"


def targets(sent: list[tuple[Request, int | None]], limit: int = MAX_TARGETS) -> list[Target]:
    """Successful GETs, one per endpoint (the last one sent: its IDs and token are valid)."""
    chosen: dict[str, Target] = {}
    for request, status in sent:
        if request.method != "GET" or status is None or status >= 400:
            continue
        name = endpoint_name(request.method, request.path)
        headers = {k: v for k, v in request.headers.items() if k.lower() in SAFE_HEADERS}
        chosen[name] = Target(name, request.method, request.path, headers)
    return list(chosen.values())[:limit]


def script(base_url: str, items: list[Target], vus: int, duration_s: int, summary_path: str) -> str:
    """A k6 script that requests every target in turn, tagged by endpoint, and writes the full summary as JSON."""
    reqs = [{"name": t.name, "method": t.method, "url": base_url + t.path, "headers": t.headers} for t in items]
    thresholds = {f"http_req_duration{{name:{t.name}}}": ["max>=0"] for t in items}  # makes k6 keep each endpoint
    return f"""import http from "k6/http";

const REQS = {json.dumps(reqs)};
export const options = {{
  vus: {vus},
  duration: "{duration_s}s",
  thresholds: {json.dumps(thresholds)},
  summaryTrendStats: ["avg", "min", "med", "p(95)", "p(99)", "max"],
}};

export default function () {{
  for (const r of REQS) {{
    http.request(r.method, r.url, null, {{ headers: r.headers, tags: {{ name: r.name }} }});
  }}
}}

export function handleSummary(data) {{
  return {{ "{summary_path}": JSON.stringify(data) }};
}}
"""


def _ms(values: dict[str, Any], key: str) -> float | None:
    v = values.get(key)
    return round(float(v), 2) if isinstance(v, int | float) else None


def read_summary(data: dict[str, Any]) -> dict[str, Any]:
    """k6's summary → overall and per-endpoint latency (ms), requests per second, failure rate."""
    metrics = data.get("metrics", {})
    duration = metrics.get("http_req_duration", {}).get("values", {})
    reqs = metrics.get("http_reqs", {}).get("values", {})
    failed = metrics.get("http_req_failed", {}).get("values", {})
    endpoints: list[dict[str, Any]] = []
    for key, metric in metrics.items():
        m = re.fullmatch(r"http_req_duration\{name:(.+)\}", key)
        if m:
            v = metric.get("values", {})
            endpoints.append({"endpoint": m.group(1), "avg_ms": _ms(v, "avg"), "p95_ms": _ms(v, "p(95)"),
                              "max_ms": _ms(v, "max")})  # fmt: skip
    endpoints.sort(key=lambda e: -float(e["p95_ms"] or 0))
    return {
        "requests": int(reqs.get("count", 0)),
        "rps": round(float(reqs.get("rate", 0)), 1),
        "failed_rate": round(float(failed.get("rate", 0)), 4),
        "avg_ms": _ms(duration, "avg"),
        "med_ms": _ms(duration, "med"),
        "p95_ms": _ms(duration, "p(95)"),
        "p99_ms": _ms(duration, "p(99)"),
        "endpoints": endpoints,
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Change in p95 and throughput, overall and per endpoint (negative ms is faster)."""

    def delta(a: float | None, b: float | None) -> dict[str, float | None]:
        if a is None or b is None:
            return {"before": a, "after": b, "change_pct": None}
        return {"before": a, "after": b, "change_pct": round(100 * (b - a) / a, 1) if a else None}

    old = {e["endpoint"]: e for e in before.get("endpoints", [])}
    return {
        "p95_ms": delta(before.get("p95_ms"), after.get("p95_ms")),
        "rps": delta(before.get("rps"), after.get("rps")),
        "endpoints": [
            {"endpoint": e["endpoint"], **delta(old[e["endpoint"]]["p95_ms"], e["p95_ms"])}
            for e in after.get("endpoints", [])
            if e["endpoint"] in old
        ],
    }
