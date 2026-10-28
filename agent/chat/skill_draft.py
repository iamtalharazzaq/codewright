"""Drafting a custom skill (CODEWRIGHT.md Section 8.6.2): `/create-skill <description>` or "save this as a skill".

The model fills a small schema; the SKILL.md is rendered from it here, so the result always parses. The draft is
shown on a card and saved only when the user approves it (the Skills screen can edit it further).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from agent.llm.client import LLMClient
from agent.llm.client import Message as LLMMessage
from agent.llm.structured import structured
from agent.skills import Language, SkillMeta, render

SAVE_AS_SKILL = re.compile(
    r"\b(save|turn|make)\s+(this|that|it|these steps|the (?:last|previous) \w+)?\s*(as|into)\s+(a\s+|my\s+)?"
    r"(new\s+|custom\s+)?skill\b",
    re.I,
)
# How each language is named in a conversation: a draft keeps a language only when the user named it.
LANGUAGE_NAMES: dict[str, str] = {
    "python": r"python|\.py\b|django|flask|fastapi|pytest",
    "go": r"\bgo(lang)?\b|\.go\b|gin\b",
    "typescript": r"typescript|\.tsx?\b|\bts\b|angular|next\.?js",
    "javascript": r"javascript|\.jsx?\b|\bjs\b|node(\.?js)?\b|express|react",
    "cpp": r"c\+\+|\bcpp\b|cmake|\.(cc|cpp|hpp|h)\b",
}
HISTORY_TURNS = 6
TURN_CHARS = 800


# What a drafted skill may run: the read-only playbooks, a snippet, or an answer that follows its steps. Skills that
# change a project (add_feature, refactor...) are written on the Skills screen, where their inputs can be set.
DraftPlaybook = Literal["review_code", "explain_code", "write_docs", "analyze_audit", "write_code", "custom"]


class SkillDraftOut(BaseModel):
    name: str = Field(description="Short kebab-case name, e.g. 'go-error-review'.")
    title: str = Field(description="Human title, at most 5 words.")
    description: str = Field(description="What it does and when to use it, one or two sentences.")
    playbook: DraftPlaybook = Field(
        description="review_code for reviews, explain_code for explanations, write_docs for docs, analyze_audit "
        "for audits, write_code for snippets, custom for anything else (an answer that follows the steps)."
    )
    languages: list[Language] = Field(default_factory=list, description="Only if it is for specific languages.")
    steps: list[str] = Field(min_length=2, max_length=8, description="What to do, one short imperative each.")
    output_format: str = Field(description="How the result should look, one sentence.")


SYSTEM = """You design a reusable "skill" for Codewright, an AI software team: a named procedure the user can run
again with a slash command. Reply with JSON only. Keep the user's own rules and wording; make steps concrete and
checkable. Never include secrets, passwords or tokens."""


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return s if len(s) >= 2 and s[0].isalpha() else f"skill-{s}".strip("-")[:40]


async def draft(
    client: LLMClient,
    request: str,
    history: Sequence[LLMMessage] = (),
    *,
    scope: str = "global",
) -> str:
    """A SKILL.md draft from a description and/or the conversation so far."""
    convo = "\n".join(f"{m['role']}: {m['content'][:TURN_CHARS]}" for m in history[-HISTORY_TURNS:])
    user = (f"The conversation to turn into a skill:\n{convo}\n\n" if convo else "") + (
        f"What the user wants the skill to do: {request}" if request else "Make a skill that repeats what was done."
    )
    result = await structured(
        client,
        SkillDraftOut,
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        task="draft_skill",
        max_tokens=700,
    )
    out = result.value
    name = slug(out.name or out.title)
    meta = SkillMeta(
        name=name,
        command=f"/{name}",
        title=out.title.strip()[:60],
        description=out.description.strip()[:500]
        if len(out.description.strip()) >= 10
        else f"{out.title}: {request}"[:500],
        languages=[lang for lang in out.languages if re.search(LANGUAGE_NAMES[lang], user, re.I)],
        scope=scope,
        playbook=out.playbook,
        tier=0,
        allowed_tools=["read_files", "graph_query", "code_search"]
        + (["run_linters"] if out.playbook == "review_code" else []),
        output=out.output_format.strip()[:60] or "markdown",
    )
    steps = "\n".join(f"{i}. {s.strip()}" for i, s in enumerate(out.steps, 1))
    return render(meta, f"## Instructions\n{steps}\n\n## Output format\n{out.output_format.strip()}")
