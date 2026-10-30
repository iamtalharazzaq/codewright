"""Intent Router (CODEWRIGHT.md Section 4, component 1): message → intent, tier, targets, confidence.

Order: slash command (no model call) → unsupported language (declined, no model call) → one structured model call.
The model only classifies; tiers come from `config/tiers.yaml`, raised by app/change size where the spec allows.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from agent.chat.intents import (
    Intent,
    LanguageDecline,
    intent_config,
    parse_slash,
    router_settings,
    unsupported_language,
)
from agent.llm.client import LLMClient, Message, Usage
from agent.llm.structured import structured

Size = Literal["small", "medium", "large"]


class RouterOutput(BaseModel):
    intent: Intent | Literal["off_topic"] = Field(description="The best intent, or off_topic if not about software.")
    confidence: float = Field(ge=0, le=1, description="0-1: how sure you are.")
    size: Size = Field(
        description="small: one function/file or a tiny app; medium: multi-screen app or a module; large: a system."
    )
    targets: list[str] = Field(default_factory=list, max_length=5, description="Files, folders, modules named.")
    clarifying_question: str = Field(default="", description="One short question if the request is unclear.")
    skill: str = Field(default="", description="The name of the user's skill this message asks for, or empty.")


@dataclass(frozen=True)
class Route:
    """Where a message goes. `decline` is set for unsupported languages and non-software requests."""

    intent: Intent | None
    tier: int
    confidence: float
    targets: list[str] = field(default_factory=list)
    args: str = ""  # slash-command arguments
    command: str | None = None  # the slash command used, if any
    question: str | None = None  # ask this instead of acting (low confidence)
    decline: str | None = None
    skill: str | None = None  # a custom skill the model matched (Section 8.6.3); the chat confirms it by keywords
    usage: Usage = field(default_factory=Usage)


SYSTEM = """You classify one message sent to Codewright, an AI software team. Reply with JSON only.

Intents:
- general_help: a question about software concepts, tools or Codewright itself; nothing is made ("What's a saga?")
- project_manage: connect/list/status/deliver a project ("Connect my repo", "deliver to GitHub")
- explain_code: explain how existing code works ("How does checkout work?")
- analyze_audit: audit an existing project's architecture/quality ("Audit my architecture")
- write_docs: document existing code ("Document this API")
- write_tests: add tests to existing code ("Add tests for orders")
- fix_bug: something in existing code is broken ("Login fails with 500", "wrong result for 0.1 + 0.2")
- security_review: check existing code for security issues ("Is my store app secure?")
- refactor: restructure existing code, same behavior ("Refactor the order code")
- improve_performance: existing code is slow ("My API is slow when listing products")
- upgrade: upgrade a framework/dependency version ("Upgrade to Django 5")
- database_change: index, schema or database engine change ("Add an index", "MySQL to Postgres")
- add_feature: add a feature to an existing app ("Add a score counter to my tic-tac-toe")
- frontend_modernize: new framework or modern look for an existing frontend ("Make the to-do app look modern")
- devops_deploy: Docker, CI/CD, deployment ("Dockerize my blog")
- translate_language: rewrite existing code in another language ("Rewrite this Python CLI in Go")
- change_architecture: modules, modular monolith, microservices, merge services, serverless, event-driven
- new_app: make a new app, game, website, script or tool ("Make a calculator", "Create a booking app")
- write_code: a standalone function, algorithm, data structure or query ("Reverse a linked list", "LRU cache")
- review_code: review code or a PR and report findings ("Review my payment module", "Find bugs in my calculator")
- off_topic: not about software (recipes, weather, politics...)

Rules:
- "Make/build/create" an app, game, site or tool → new_app. A single function/algorithm/exercise → write_code.
- Questions about concepts → general_help, even when they mention code.
- size: new_app small = single-purpose app (tic-tac-toe, calculator); medium = several screens, backend, login;
  large = a full system with many roles. For other intents use small unless clearly bigger.
- confidence below 0.6 only when the message is genuinely ambiguous; then write clarifying_question."""


def _tier(intent: Intent, size: Size, targets: Sequence[str], text: str) -> int:
    cfg = intent_config(intent)
    if intent == "new_app":
        return {"small": 1, "medium": 2, "large": 3}[size]
    if intent == "change_architecture":
        lowered = text.lower()
        return 3 if "microservice" in lowered or size == "large" else cfg.tier
    if intent == "review_code" and any(w in text.lower() for w in ("fix", "apply")):
        return max(1, cfg.tier)
    if intent == "security_review" and "fix" in text.lower():
        return cfg.max_tier
    return cfg.tier


async def route(
    client: LLMClient,
    text: str,
    *,
    history: Sequence[Message] = (),
    has_project: bool = False,
    skills: Sequence[tuple[str, str]] = (),
) -> Route:
    """Classify one user message. `history` gives the last few turns for follow-ups ("now in Python").
    `skills` are the user's custom skills that may be used automatically, as (name, description)."""
    slash = parse_slash(text)
    if slash is not None:
        cfg = intent_config(slash.intent)
        decline = unsupported_language(slash.args) if slash.args else None
        if decline:
            return _declined(decline)
        return Route(
            slash.intent,
            cfg.tier,
            1.0,
            targets=[slash.args] if slash.args else [],
            args=slash.args,
            command=slash.command,
        )

    decline = unsupported_language(text)
    if decline:
        return _declined(decline)

    context = "\n".join(f"{m['role']}: {m['content'][:300]}" for m in history[-4:])
    user = (
        f"Earlier in the chat:\n{context}\n\n" if context else ""
    ) + f"Project attached: {'yes' if has_project else 'no'}\nMessage: {text}"
    if skills:
        listing = "\n".join(f"- {name}: {desc[:160]}" for name, desc in skills[:12])
        user += (
            "\n\nThe user's own skills (set `skill` to one name only if the message clearly asks for what it does):\n"
            + listing
        )
    result = await structured(
        client,
        RouterOutput,
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        task="route_intent",
        max_tokens=200,
    )
    out = result.value
    if not has_project and out.intent in _NOT_NEW and _MAKE_AN_APP.match(text.strip()):
        out.intent = "new_app"  # "Make a to-do list app" with nothing attached is a new app, whatever the model said
    if out.intent == "off_topic":
        return Route(
            None,
            0,
            out.confidence,
            decline="I can only help with software: questions, code, apps and projects. What would you like to build "
            "or understand?",
            usage=result.usage,
        )
    question = None
    if out.confidence < router_settings()["min_confidence"]:
        question = out.clarifying_question or "Could you say a bit more about what you'd like me to do?"
    return Route(
        out.intent,
        _tier(out.intent, out.size, out.targets, text),
        out.confidence,
        targets=out.targets,
        question=question,
        skill=out.skill if out.skill and out.skill in {n for n, _ in skills} else None,
        usage=result.usage,
    )


_NOT_NEW = {"write_code", "add_feature", "frontend_modernize"}
_MAKE_AN_APP = re.compile(
    r"^(please\s+)?(make|build|create|develop)\s+(me\s+)?(a|an|my)\s+(?!function\b|algorithm\b)[\w\s\-/']{0,60}?"
    r"\b(app|application|game|website|site|page|tool|tracker|timer|calculator|generator|converter|previewer|"
    r"manager|system|platform|script|bot|dashboard)\b",
    re.I,
)


def _declined(decline: LanguageDecline) -> Route:
    return Route(None, 0, 1.0, decline=decline.message)
