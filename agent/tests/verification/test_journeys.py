"""Journeys (CODEWRIGHT.md Phase 7 tasks 2-3): route-syntax normalization, `{{var}}` substitution and picking a
value saved from an earlier answer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.verification.journeys import Journey, Missing, Step, fill, journeys_from_json, normalize, pick, save_journeys


def test_normalize_handles_gin_flask_and_nextjs_syntax() -> None:
    assert normalize("/items/:id") == "/items/{id}"
    assert normalize("/items/<int:id>") == "/items/{id}"
    assert normalize("/items/[id]") == "/items/{id}"


def test_fill_substitutes_saved_variables() -> None:
    assert fill({"token": "{{token}}", "n": 1}, {"token": "abc"}) == {"token": "abc", "n": 1}
    assert fill("Bearer {{token}}", {"token": "abc"}) == "Bearer abc"
    with pytest.raises(Missing):
        fill("{{missing}}", {})


def test_pick_walks_a_simple_json_path() -> None:
    data = {"data": {"items": [{"id": "x"}, {"id": "y"}]}}
    assert pick(data, "$.data.items[0].id") == "x"
    assert pick(data, "$.data.items[1].id") == "y"


def test_journeys_json_round_trip(tmp_path: Path) -> None:
    journeys = [
        Journey("login", [Step("log in", "POST", "/auth/login", {"email": "a@b.com"}, save={"token": "$.token"})])
    ]
    path = tmp_path / "journeys.json"
    save_journeys(journeys, path)
    back = journeys_from_json(json.loads(path.read_text(encoding="utf-8")))
    assert back[0].name == "login"
    assert back[0].steps[0].save == {"token": "$.token"}
