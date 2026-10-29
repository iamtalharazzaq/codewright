"""Missing-info check and Confirm card (CODEWRIGHT.md Section 3.4, EXAMPLES.md Section 1).

One structured call compares the request (plus earlier answers and known preferences) with the intent's required
info and returns the questions still open, each with a default, and a draft confirm card. Code enforces the rules a
small model may miss: the language question for anything new (C18), at most 5 questions, at most 2 rounds.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from agent.chat.intents import INTENT_LABELS, Intent, intent_config, named_language, router_settings
from agent.llm.client import LLMClient, Usage
from agent.llm.structured import structured
from agent.playbooks.new_app.stacks import (
    CI_QUESTION,
    PLATFORM_QUESTION,
    PLATFORMS,
    answer_to,
    default_platform,
    extras,
    platform_stated,
)

Language = Literal["Python", "TypeScript", "JavaScript", "Go", "C++"]


class Question(BaseModel):
    question: str = Field(description="One short question.")
    default: str = Field(description="The answer used if the user says defaults are fine.")
    options: list[str] = Field(default_factory=list, max_length=6, description="Choices, if it's a pick-one.")
    hint: str = Field(default="", description="Optional: why the default fits, under 10 words.")


class ConfirmCard(BaseModel):
    # No max_length here: llama.cpp's grammar cuts a string mid-word at the limit. `_tidy` shortens at a word instead.
    what: str = Field(description="One sentence: what I'll make or do.")
    stack: str = Field(description="Language and main tools in 2-6 words, e.g. 'Python 3.12 + pytest'.")
    features: list[str] = Field(min_length=1, max_length=5, description="Main features or steps, 2-8 words each.")
    deliver: str = Field(description="What the user gets at the end, in a few words.")


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:(")
    return cut + "…"


def _tidy(card: ConfirmCard) -> ConfirmCard:
    return ConfirmCard(
        what=_clip(card.what, 200),
        stack=_clip(card.stack, 60),
        features=[_clip(f, 90) for f in card.features],
        deliver=_clip(card.deliver, 140),
    )


class IntakeOutput(BaseModel):
    recommended_language: Language = Field(description="The best of the five languages for this request.")
    language_reason: str = Field(description="Why, in at most 8 words.")
    questions: list[Question] = Field(
        default_factory=list, max_length=3, description="Only what is still missing and matters; most important first."
    )
    card: ConfirmCard


@dataclass(frozen=True)
class Intake:
    """`questions` empty → show the confirm card now."""

    questions: list[Question]
    card: ConfirmCard
    language: str | None
    usage: Usage = field(default_factory=Usage)


SYSTEM = """You are the Clarifier of Codewright, an AI software team. Before any work starts you check what is still
missing from a request, and draft the confirm card. Reply with JSON only.

Rules:
- Ask only about required info that is missing AND would change the result a lot. At most 3 questions; zero is
  fine. Small things (who uses a simple app, the platform when it's obvious, style) get a default in the card, not a
  question.
- Every question has a sensible default. Give `options` (2-6 short choices, the default among them) for every
  pick-one question, such as the platform, the framework or the style: the user answers them from a dropdown. Leave
  `options` empty only for a free-text answer.
- Don't ask about the language: that is handled separately. Don't re-ask anything already answered.
- The card describes exactly what will be made, using the answers, and the defaults for anything unanswered.
- Codewright works only in Python, TypeScript, JavaScript, Go and C++."""


async def check(
    client: LLMClient,
    intent: Intent,
    request: str,
    *,
    answers: Sequence[tuple[str, str]] = (),
    preferences: Sequence[str] = (),
    project_language: str | None = None,
    round_no: int = 1,
) -> Intake:
    """Run the missing-info check for one round. `answers` are (questions asked, user's reply) from earlier rounds."""
    cfg = intent_config(intent)
    said = " ".join([request, *(a for _, a in answers)])
    language = project_language or named_language(said)
    lines = [
        f"Request type: {INTENT_LABELS[intent]}",
        f"Request: {request}",
        "Required info: " + ("; ".join(cfg.required) or "none"),
        f"What the user gets: {cfg.deliver}",
    ]
    if language:
        lines.append(f"Language: {language} (decided)")
    for asked, reply in answers:
        lines.append(f"Asked: {asked}\nUser answered: {reply}")
    if preferences:
        lines.append("Known preferences: " + "; ".join(preferences))
    if round_no >= router_settings()["max_rounds"]:
        lines.append("This is the last round: ask nothing more; fill every gap with defaults.")

    result = await structured(
        client,
        IntakeOutput,
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}],
        task="intake_check",
        max_tokens=700,
    )
    out = result.value
    out.card = _tidy(out.card)
    last_round = round_no >= router_settings()["max_rounds"]
    questions = [] if last_round else list(out.questions)
    asked_language = cfg.new and not language and not last_round
    if cfg.new and not language:
        if last_round:
            language = out.recommended_language
        else:
            questions.insert(0, _language_question(out.recommended_language, out.language_reason))
    if intent == "new_app" and not last_round:
        at = 1 if asked_language else 0
        inputs = {"request": request, "answers": [list(a) for a in answers]}
        questions = [q for q in questions if "platform" not in q.question.lower() and q.question != CI_QUESTION]
        if not platform_stated(inputs):
            questions.insert(at, _platform_question(default_platform(inputs)))
            at += 1
        if not _ci_decided(request, answers):
            questions.insert(at, _ci_question())
    if language and cfg.new and language.lower() not in out.card.stack.lower():
        out.card.stack = f"{language} · {out.card.stack}"
    limit = router_settings()["max_questions_per_round"]
    return Intake(questions[:limit], out.card, language, result.usage)


def _language_question(recommended: str, reason: str) -> Question:
    others = [lang for lang in ("Python", "TypeScript", "JavaScript", "Go", "C++") if lang != recommended]
    return Question(
        question="Which language?",
        default=recommended,
        options=[recommended, *others],
        hint=_clip(reason, 80).rstrip("."),
    )


def _ci_decided(request: str, answers: Sequence[tuple[str, str]]) -> bool:
    """CI is asked once: not again after an answer, nor when the request itself says whether it wants it."""
    inputs = {"request": request, "answers": [list(a) for a in answers]}
    return answer_to(inputs, CI_QUESTION) is not None or extras(inputs).ci


def _ci_question() -> Question:
    return Question(
        question=CI_QUESTION,
        default="No",
        options=["No", "Yes"],
        hint="a workflow that runs the tests on every push",
    )


def _platform_question(default: str) -> Question:
    return Question(
        question=PLATFORM_QUESTION,
        default=default,
        options=list(PLATFORMS),
        hint="where the app runs",
    )
