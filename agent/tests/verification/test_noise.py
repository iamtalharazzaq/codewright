"""Noise rules (CODEWRIGHT.md Section 5.18): glob matching, the built-ins' explanations, and save/load round trips."""

from __future__ import annotations

from pathlib import Path

from agent.verification.noise import NoiseRules, Rule, generic, glob


def test_generic_replaces_array_indexes() -> None:
    assert generic("$.items[3].id") == "$.items[#].id"


def test_glob_star_is_one_segment_double_star_is_any() -> None:
    assert glob("**.created_at").fullmatch("$.data[#].created_at")
    assert glob("*.id").fullmatch("data.id")
    assert glob("*.id").fullmatch("data.nested.id")  # a bare "*" pattern matches any path ending that way
    assert not glob("$.*.id").fullmatch("$.data.nested.id")  # anchored at "$": one segment only
    assert glob("header:*").fullmatch("header:x-request-id")


def test_explain_finds_timestamps_tokens_and_ids() -> None:
    rules = NoiseRules()
    assert rules.explain("$.created_at", "2024-01-01T00:00:00Z", "2024-06-01T00:00:00Z") is not None
    assert rules.explain("$.token", "a" * 30, "b" * 30) is not None
    uuid_a, uuid_b = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    assert rules.explain("$.id", uuid_a, uuid_b) is not None
    assert rules.explain("$.id", "not-an-id", uuid_b) is None  # different kinds of value: a real change


def test_explain_respects_disabled_rules() -> None:
    rules = NoiseRules()
    next(r for r in rules.rules if r.id == "timestamps").enabled = False
    assert rules.explain("$.created_at", "2024-01-01T00:00:00Z", "2024-06-01T00:00:00Z") is None


def test_float_tolerance() -> None:
    rules = NoiseRules()
    assert rules.explain("$.total", 19.990000001, 19.99) is not None
    assert rules.explain("$.total", 19.99, 20.5) is None


def test_save_and_load_round_trips_choices_and_own_rules(tmp_path: Path) -> None:
    rules = NoiseRules()
    next(r for r in rules.rules if r.id == "array-order").enabled = True  # off by default
    next(r for r in rules.rules if r.id == "timestamps").enabled = False  # on by default
    rules.rules.append(Rule("my-rule", "ignore", "A custom header", where="header:x-trace"))
    path = tmp_path / "noise.json"
    rules.save(path)

    back = NoiseRules.load(path)
    assert back.enabled("array-order")
    assert not back.enabled("timestamps")
    assert back.enabled("my-rule")
    assert not any(r.builtin for r in back.rules if r.id == "my-rule")


def test_load_missing_file_gives_defaults(tmp_path: Path) -> None:
    rules = NoiseRules.load(tmp_path / "missing.json")
    assert rules.enabled("generated-ids")
    assert not rules.enabled("array-order")
