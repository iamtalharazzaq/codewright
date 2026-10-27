"""Missing-info check and Confirm card (CODEWRIGHT.md Section 3.4, EXAMPLES.md Section 1).

One structured call compares the request (plus earlier answers and known preferences) with the intent's required
info and returns the questions still open, each with a default, and a draft confirm card. Code enforces the rules a
small model may miss: the language question for anything new (C18), at most 5 questions, at most 2 rounds.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from agent.chat.intents import INTENT_LABELS, Intent, intent_config, named_language, router_settings
from agent.llm.client import LLMClient, Usage
from agent.llm.structured import structured

Language = Literal["Python", "TypeScript", "JavaScript", "Go", "C++"]


class Question(BaseModel):
    question: str = Field(description="One short question.")
    default: str = Field(description="The answer used if the user says defaults are fine.")
    options: list[str] = Field(default_factory=list, max_length=6, description="Choices, if it's a pick-one.")
    hint: str = Field(default="", max_length=80, description="Optional: why the default fits, under 10 words.")


Short = Annotated[str, Field(max_length=70)]


class ConfirmCard(BaseModel):
    what: str = Field(max_length=160, description="One sentence: what I'll make or do.")
    stack: str = Field(max_length=80, description="Language and main tools in 2-6 words, e.g. 'Python 3.12 + pytest'.")
    features: list[Short] = Field(min_length=1, max_length=5, description="Main features or steps, 2-8 words each.")
    deliver: str = Field(max_length=120, description="What the user gets at the end, in a few words.")


class IntakeOutput(BaseModel):
    recommended_language: Language = Field(description="The best of the five languages for this request.")
    language_reason: str = Field(max_length=80, description="Why, in at most 8 words.")
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
- Every question has a sensible default. Use options for pick-one questions.
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
    last_round = round_no >= router_settings()["max_rounds"]
    questions = [] if last_round else list(out.questions)
    if cfg.new and not language:
        if last_round:
            language = out.recommended_language
        else:
            questions.insert(0, _language_question(out.recommended_language, out.language_reason))
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
        hint=reason.rstrip("."),
    )
