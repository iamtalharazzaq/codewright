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
    ADDITIONS,
    ADDITIONS_QUESTION,
    FRONTEND_QUESTION,
    FRONTENDS,
    PLATFORM_QUESTION,
    PLATFORMS,
    additions_default,
    answer_to,
    default_platform,
    frontend_default,
    frontend_open,
    platform_stated,
)

Language = Literal["Python", "TypeScript", "JavaScript", "Go", "C++"]


class Question(BaseModel):
    question: str = Field(description="One short question.")
    default: str = Field(description="The answer used if the user says defaults are fine.")
    options: list[str] = Field(default_factory=list, max_length=6, description="Choices, if it's a pick-one.")
    hint: str = Field(default="", description="Optional: why the default fits, under 10 words.")
    multi: bool = Field(default=False, description="Tick-boxes: any number of the options, the default a comma list.")


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
            questions.insert(0, _language_question(out.recommended_language))
    if intent == "new_app" and not last_round:
        questions = _new_app_questions(
            questions, request, answers, asked_language, frontend=frontend_default(out.recommended_language)
        )
    if language and cfg.new and language.lower() not in out.card.stack.lower():
        out.card.stack = f"{language} · {out.card.stack}"
    limit = router_settings()["max_questions_per_round"]
    return Intake(questions[:limit], out.card, language, result.usage)


def _new_app_questions(
    asked: list[Question], request: str, answers: Sequence[tuple[str, str]], after_language: bool, *, frontend: str
) -> list[Question]:
    """What a new app always asks, in code (the model may miss it): platform, frontend, CI and the extras. The
    model's own questions about these are dropped; what the request or an earlier answer settled is not asked."""
    inputs = {"request": request, "answers": [list(a) for a in answers]}
    questions = [
        q
        for q in asked
        if not {"platform", "frontend"} & set(q.question.lower().split())
        and q.question not in (FRONTEND_QUESTION, ADDITIONS_QUESTION)
    ]
    ours: list[Question] = []
    if not platform_stated(inputs):
        ours.append(_platform_question(default_platform(inputs)))
    if frontend_open(inputs):
        ours.append(_frontend_question(frontend))
    if answer_to(inputs, ADDITIONS_QUESTION) is None:
        ours.append(_additions_question(request))
    at = 1 if after_language else 0
    return [*questions[:at], *ours, *questions[at:]]


def _language_question(recommended: str) -> Question:
    others = [lang for lang in ("Python", "TypeScript", "JavaScript", "Go", "C++") if lang != recommended]
    return Question(
        question="Which language?",
        default=recommended,
        options=[recommended, *others],
    )


def _platform_question(default: str) -> Question:
    return Question(
        question=PLATFORM_QUESTION,
        default=default,
        options=list(PLATFORMS),
    )


def _frontend_question(default: str) -> Question:
    return Question(question=FRONTEND_QUESTION, default=default, options=list(FRONTENDS))


def _additions_question(request: str) -> Question:
    return Question(
        question=ADDITIONS_QUESTION, default=additions_default(request), options=list(ADDITIONS), multi=True
    )
