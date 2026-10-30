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


def _names(result: intake.Intake) -> list[str]:
    return [q.question for q in result.questions]


async def test_intake_always_asks_the_language_for_new_work() -> None:
    reply = {
        "recommended_language": "TypeScript",
        "language_reason": "runs in the browser",
        "questions": [],
        "card": CARD,
    }
    client, _ = client_returning(json.dumps(reply))
    result = await intake.check(client, "new_app", "Make a calculator")
    assert _names(result) == ["Which language?", "Which platform?", "Which frontend?", "Additional things to be added"]
    assert result.questions[0].options[0] == "TypeScript"
    assert result.questions[1].options == [
        "Browser app",
        "Terminal (command line)",
        "API (REST)",
        "Library (functions only)",
    ]
    assert result.questions[2].options[0] == "React + TypeScript" and result.questions[2].options[-1] == "None"
    extra = result.questions[3]
    assert extra.multi and extra.default == "Test cases (backend)"
    assert extra.options == [
        "CI workflow (GitHub Actions)",
        "README file",
        "Graphify",
        "Test cases (backend)",
        "Test cases (frontend)",
    ]
    assert all(q.hint == "" for q in result.questions)  # no description under a field


async def test_intake_ticks_what_the_request_already_asks_for_and_skips_what_is_answered() -> None:
    reply = {"recommended_language": "Python", "language_reason": "x", "questions": [], "card": CARD}
    client, _ = client_returning(json.dumps(reply))
    asked = await intake.check(client, "new_app", "Make a terminal calculator in Python with CI and a README")
    assert _names(asked) == ["Additional things to be added"]  # terminal: no platform, no frontend
    assert asked.questions[0].default == "CI workflow (GitHub Actions), README file, Test cases (backend)"
    client, _ = client_returning(json.dumps(reply))
    done = await intake.check(
        client,
        "new_app",
        "Make a terminal calculator in Python",
        answers=[("x", "Additional things to be added README file")],
    )
    assert done.questions == []
    client, _ = client_returning(json.dumps(reply))
    other = await intake.check(client, "add_feature", "Add a button in Python")
    assert all("Additional" not in q.question for q in other.questions)


async def test_intake_last_round_shows_the_card_with_the_named_language() -> None:
    q = {"question": "Basic or scientific?", "default": "basic", "options": []}
    reply = {"recommended_language": "TypeScript", "language_reason": "x", "questions": [q], "card": CARD}
    client, _ = client_returning(json.dumps(reply))
    result = await intake.check(
        client, "new_app", "Make a calculator", answers=[("Which language?", "Python, basic")], round_no=2
    )
    assert result.questions == [] and result.language == "Python"
    assert result.card.stack.startswith("Python")


async def test_intake_asks_the_platform_with_the_rules_default_and_not_when_it_is_stated() -> None:
    reply = {"recommended_language": "Python", "language_reason": "x", "questions": [], "card": CARD}
    client, _ = client_returning(json.dumps(reply))
    asked = await intake.check(client, "new_app", "A script that renames files in Python")
    platform = next(q for q in asked.questions if q.question == "Which platform?")
    assert platform.default == "Terminal (command line)"
    client, _ = client_returning(json.dumps(reply))
    stated = await intake.check(client, "new_app", "A website for my bakery in TypeScript")
    assert all(q.question != "Which platform?" for q in stated.questions)


async def test_intake_asks_for_the_frontend_once_and_not_for_a_terminal_app() -> None:
    reply = {"recommended_language": "JavaScript", "language_reason": "x", "questions": [], "card": CARD}
    client, _ = client_returning(json.dumps(reply))
    web = await intake.check(client, "new_app", "A todo website in JavaScript")
    assert "Which frontend?" in _names(web)
    assert next(q for q in web.questions if q.question == "Which frontend?").default == "React + JavaScript"
    client, _ = client_returning(json.dumps(reply))
    terminal = await intake.check(client, "new_app", "A terminal todo list in JavaScript")
    assert "Which frontend?" not in _names(terminal)
    client, _ = client_returning(json.dumps(reply))
    answered = await intake.check(
        client,
        "new_app",
        "A todo website in JavaScript",
        answers=[("x", "Which frontend? None\nAdditional things to be added README file")],
    )
    assert "Which frontend?" not in _names(answered) and "Additional things to be added" not in _names(answered)


async def test_the_card_promises_only_what_was_ticked() -> None:
    reply = {"recommended_language": "Python", "language_reason": "x", "questions": [], "card": CARD}
    reply_text = "Which language? Python\nAdditional things to be added README file, Test cases (backend)"
    client, _ = client_returning(json.dumps(reply))
    some = await intake.check(client, "new_app", "A calculator", answers=[("x", reply_text)], round_no=2)
    assert some.card.deliver == "A working app in Preview, tests, GUIDE.md, a README and a Done card"
    client, _ = client_returning(json.dumps(reply))
    none = await intake.check(
        client, "new_app", "A calculator", answers=[("x", "Additional things to be added ")], round_no=2
    )
    assert none.card.deliver == "A working app in Preview, GUIDE.md and a Done card"
