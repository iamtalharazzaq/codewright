"""Router, missing-info check and the deterministic language/slash rules (CODEWRIGHT.md Sections 3.4 and 4)."""

from __future__ import annotations

import json

import pytest

from agent.chat import intake, router
from agent.chat.intents import named_language, parse_slash, unsupported_language
from agent.tests.llm.test_structured import client_returning


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Reverse a linked list in Java", "java"),
        ("Make a calculator in PHP", "php"),
        ("Review my Java project", "java"),
        ("Write code in C#", "c#"),
        ("Rewrite this in Rust", "rust"),
    ],
)
def test_unsupported_languages_are_declined_with_a_suggestion(text: str, language: str) -> None:
    decline = unsupported_language(text)
    assert decline is not None and decline.language == language
    assert "isn't supported" in decline.message and decline.suggestions


@pytest.mark.parametrize("text", ["What is Java?", "Make tic-tac-toe in Go", "Write it in TypeScript"])
def test_questions_and_supported_languages_are_not_declined(text: str) -> None:
    assert unsupported_language(text) is None


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("C++, both", "C++"),
        ("Python, basic is fine", "Python"),
        ("in Go", "Go"),
        ("go ahead", None),
        ("let's go", None),
    ],
)
def test_named_language(text: str, language: str | None) -> None:
    assert named_language(text) == language


def test_slash_commands() -> None:
    cmd = parse_slash("/review-code internal/payment")
    assert cmd is not None and cmd.intent == "review_code" and cmd.args == "internal/payment"
    assert parse_slash("/nope x") is None


async def test_router_skips_the_model_for_slash_commands_and_declines() -> None:
    client, bodies = client_returning()
    route = await router.route(client, "/write-code fizzbuzz")
    assert (route.intent, route.tier, route.command) == ("write_code", 1, "write-code")
    declined = await router.route(client, "Make a calculator in PHP")
    assert declined.intent is None and declined.decline
    assert bodies == []


@pytest.mark.parametrize(
    ("answer", "intent", "tier", "question", "decline"),
    [
        ({"intent": "new_app", "confidence": 0.9, "size": "medium"}, "new_app", 2, None, False),
        ({"intent": "change_architecture", "confidence": 0.9, "size": "small"}, "change_architecture", 3, None, False),
        ({"intent": "off_topic", "confidence": 0.9, "size": "small"}, None, 0, None, True),
        (
            {"intent": "general_help", "confidence": 0.3, "size": "small", "clarifying_question": "Which app?"},
            "general_help",
            0,
            "Which app?",
            False,
        ),
    ],
)
async def test_router_tiers_and_low_confidence(
    answer: dict[str, object], intent: str | None, tier: int, question: str | None, decline: bool
) -> None:
    client, _ = client_returning(json.dumps(answer))
    route = await router.route(client, "Split my monolith into microservices")
    assert (route.intent, route.tier, route.question, bool(route.decline)) == (intent, tier, question, decline)


CARD = {"what": "A calculator.", "stack": "TypeScript + React", "features": ["Basic math"], "deliver": "An app"}


async def test_intake_always_asks_the_language_for_new_work() -> None:
    reply = {
        "recommended_language": "TypeScript",
        "language_reason": "runs in the browser",
        "questions": [],
        "card": CARD,
    }
    client, _ = client_returning(json.dumps(reply))
    result = await intake.check(client, "new_app", "Make a calculator")
    assert [q.question for q in result.questions] == ["Which language?"]
    assert result.questions[0].options[0] == "TypeScript"


async def test_intake_last_round_shows_the_card_with_the_named_language() -> None:
    q = {"question": "Basic or scientific?", "default": "basic", "options": []}
    reply = {"recommended_language": "TypeScript", "language_reason": "x", "questions": [q], "card": CARD}
    client, _ = client_returning(json.dumps(reply))
    result = await intake.check(
        client, "new_app", "Make a calculator", answers=[("Which language?", "Python, basic")], round_no=2
    )
    assert result.questions == [] and result.language == "Python"
    assert result.card.stack.startswith("Python")
