"""Corrections → USER_FACT (CODEWRIGHT.md Phase 6 task 4, Section 5.18 step 3).

"That's wrong, Payment also calls Notification" after an explanation or an As-Is is parsed into facts about modules.
They are never saved silently: the chat shows them on a card (Save / Discard), and an audit's As-Is gate saves them
when the user sends the correction as the gate's Edit comment. Saved facts are the strongest evidence on the graph.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent.llm.client import LLMClient
from agent.llm.structured import structured

Relation = Literal["calls", "uses", "depends_on", "not_calls"]

_CORRECTION = re.compile(
    r"\b(that'?s|this is|it'?s|you'?re|thats)\s+(wrong|not right|incorrect|not true|not correct)"
    r"|\bactually\b|\byou missed\b|\byou forgot\b"
    r"|\b(also|doesn'?t|does not|never|no longer)\s+(call|calls|use|uses|depend|depends|talk|talks|send|sends)\b",
    re.I,
)


def looks_like_correction(text: str) -> bool:
    return bool(_CORRECTION.search(text))


class Fact(BaseModel):
    source: str = Field(description="The module that calls/uses (as the user named it).")
    target: str = Field(description="The module being called/used.")
    relation: Relation = Field(description="calls / uses / depends_on, or not_calls when the user says it doesn't.")
    note: str = Field(default="", description="The user's words, shortened.")


class Facts(BaseModel):
    facts: list[Fact] = Field(default_factory=list, max_length=5)


SYSTEM = """You turn a user's correction about their code's architecture into facts. Reply with JSON only.
Only facts the user states about which module calls, uses or depends on which; "X doesn't call Y" is not_calls.
Use the module names from the list when they match. No facts if the message states none."""


def match_module(name: str, module_ids: Sequence[str]) -> str | None:
    """ "Payment", "payment service", "internal/payment" → internal/payment."""
    want = re.sub(r"\b(service|module|package|component|svc)s?\b", "", name.lower()).strip(" /._-")
    if not want:
        return None
    for m in module_ids:
        if m.lower() == want:
            return m
    by_label = [m for m in module_ids if m.rsplit("/", 1)[-1].lower() in (want, want.rstrip("s"), f"{want}s")]
    if by_label:
        return min(by_label, key=len)
    contains = [m for m in module_ids if want in m.lower()]
    return min(contains, key=len) if len(contains) == 1 else None


async def parse(client: LLMClient, text: str, module_ids: Sequence[str]) -> list[dict[str, Any]]:
    """The facts in a correction, mapped to module ids; names that match no module are dropped."""
    listing = ", ".join(module_ids[:60])
    result = await structured(
        client,
        Facts,
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Modules: {listing}\n\nThe user's message: {text[:1000]}"},
        ],
        task="parse_correction",
        max_tokens=300,
    )
    facts: list[dict[str, Any]] = []
    for f in result.value.facts:
        a, b = match_module(f.source, module_ids), match_module(f.target, module_ids)
        if a and b and a != b:
            facts.append({"source": a, "target": b, "relation": f.relation, "note": f.note or text[:200]})
    return facts


def describe(fact: dict[str, Any]) -> str:
    verb = {"calls": "calls", "uses": "uses", "depends_on": "depends on", "not_calls": "does not call"}
    return f"{fact['source']} {verb.get(fact['relation'], fact['relation'])} {fact['target']}"
