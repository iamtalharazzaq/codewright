"""Benchmarks (CODEWRIGHT.md Phase 7 task 4): targets are the recording's successful GETs, one per endpoint, and the
k6 summary is read into overall and per-endpoint latency."""

from __future__ import annotations

from agent.verification.bench import compare, endpoint_name, read_summary, targets
from agent.verification.traffic import Body, Request


def test_endpoint_name_replaces_ids() -> None:
    assert endpoint_name("GET", "/api/products/3f2c1a2b3c4d5e6f?page=2") == "GET /api/products/{id}"
    assert endpoint_name("GET", "/api/products/42") == "GET /api/products/{id}"
    assert endpoint_name("GET", "/api/products") == "GET /api/products"


def test_targets_keeps_only_successful_gets_one_per_endpoint() -> None:
    sent: list[tuple[Request, int | None]] = [
        (Request("GET", "/api/items/1", {"Authorization": "x"}, Body()), 200),
        (Request("GET", "/api/items/2", {}, Body()), 200),  # same endpoint, kept as the last
        (Request("POST", "/api/items", {}, Body()), 201),  # not a GET
        (Request("GET", "/api/items/3", {}, Body()), 404),  # failed
    ]
    chosen = targets(sent)
    assert [t.name for t in chosen] == ["GET /api/items/{id}"]
    assert chosen[0].path == "/api/items/2"


def test_read_summary_extracts_overall_and_per_endpoint_numbers() -> None:
    data = {
        "metrics": {
            "http_reqs": {"values": {"count": 100, "rate": 10.0}},
            "http_req_failed": {"values": {"rate": 0.0}},
            "http_req_duration": {"values": {"avg": 20.0, "med": 18.0, "p(95)": 40.0, "p(99)": 60.0}},
            "http_req_duration{name:GET /api/items}": {"values": {"avg": 20.0, "p(95)": 40.0, "max": 80.0}},
        }
    }
    summary = read_summary(data)
    assert summary["requests"] == 100 and summary["p95_ms"] == 40.0
    assert summary["endpoints"] == [{"endpoint": "GET /api/items", "avg_ms": 20.0, "p95_ms": 40.0, "max_ms": 80.0}]


def test_compare_reports_percent_change() -> None:
    before = {"p95_ms": 100.0, "rps": 10.0, "endpoints": [{"endpoint": "GET /x", "p95_ms": 100.0}]}
    after = {"p95_ms": 150.0, "rps": 10.0, "endpoints": [{"endpoint": "GET /x", "p95_ms": 150.0}]}
    result = compare(before, after)
    assert result["p95_ms"]["change_pct"] == 50.0
    assert result["endpoints"][0]["change_pct"] == 50.0
