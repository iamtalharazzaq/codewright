"""The semantic diff (CODEWRIGHT.md Section 5.18): status/header/body comparison and the regression/noise/intended
verdicts, including intents and linked values from a replay."""

from __future__ import annotations

from agent.verification.diff import Comparer, Intent
from agent.verification.noise import NoiseRules
from agent.verification.traffic import Body, Response


def response(status: int, body: object, headers: dict[str, str] | None = None) -> Response:
    kind = "json" if not isinstance(body, str) else "text"
    return Response(status, headers or {}, Body(kind, body), 1.0)  # type: ignore[arg-type]


def test_identical_answers_have_no_differences() -> None:
    comparer = Comparer(NoiseRules())
    before = response(200, {"id": "x", "name": "a"})
    assert comparer.compare("GET /x", before, response(200, {"id": "x", "name": "a"})) == []


def test_changed_field_is_a_regression_by_default() -> None:
    comparer = Comparer(NoiseRules())
    diffs = comparer.compare("GET /x", response(200, {"name": "a"}), response(200, {"name": "b"}))
    assert len(diffs) == 1 and diffs[0].verdict == "regression" and diffs[0].path == "$.name"


def test_timestamp_field_is_noise() -> None:
    comparer = Comparer(NoiseRules())
    before = response(200, {"created_at": "2024-01-01T00:00:00Z"})
    after = response(200, {"created_at": "2024-06-01T00:00:00Z"})
    diffs = comparer.compare("GET /x", before, after)
    assert len(diffs) == 1 and diffs[0].verdict == "noise" and diffs[0].rule == "timestamps"


def test_status_change_can_be_covered_by_an_intent() -> None:
    comparer = Comparer(NoiseRules(), intents=[Intent("POST /x", reason="now requires auth")])
    diffs = comparer.compare("POST /x", response(401, None), response(403, None))
    assert len(diffs) == 1 and diffs[0].verdict == "intended" and diffs[0].rule == "intent: POST /x"


def test_linked_values_are_noise_not_a_regression() -> None:
    comparer = Comparer(NoiseRules(), linked={"str:old-id": "new-id"})
    diffs = comparer.compare("GET /x", response(200, {"owner": "old-id"}), response(200, {"owner": "new-id"}))
    assert len(diffs) == 1 and diffs[0].verdict == "noise" and diffs[0].rule == "linked-values"


def test_added_and_removed_fields_are_noted() -> None:
    comparer = Comparer(NoiseRules())
    diffs = comparer.compare("GET /x", response(200, {"a": 1}), response(200, {"b": 2}))
    assert {d.note for d in diffs} == {"field removed", "field added"}


def test_unordered_rule_ignores_array_order() -> None:
    rules = NoiseRules()
    next(r for r in rules.rules if r.id == "array-order").enabled = True
    comparer = Comparer(rules)
    diffs = comparer.compare("GET /x", response(200, {"tags": ["a", "b"]}), response(200, {"tags": ["b", "a"]}))
    assert diffs[0].verdict == "noise" and diffs[0].rule == "array-order"


def test_missing_vs_present_answer_is_a_status_difference() -> None:
    comparer = Comparer(NoiseRules())
    diffs = comparer.compare("GET /x", response(200, {}), None)
    assert diffs[0].where == "status" and diffs[0].after == "no answer"
