"""The 20 intents, slash commands and the language rule (CODEWRIGHT.md Section 4, C12, C18).

Everything here is deterministic: slash commands and unsupported languages are decided before the model is asked,
so a 9B model can't get them wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

Intent = Literal[
    "general_help",
    "project_manage",
    "explain_code",
    "analyze_audit",
    "write_docs",
    "write_tests",
    "fix_bug",
    "security_review",
    "refactor",
    "improve_performance",
    "upgrade",
    "database_change",
    "add_feature",
    "frontend_modernize",
    "devops_deploy",
    "translate_language",
    "change_architecture",
    "new_app",
    "write_code",
    "review_code",
]

# Built-in slash commands (Section 2.2). Phase 6 turns these into skills, with custom ones added by the user.
SLASH_COMMANDS: dict[str, tuple[Intent, str]] = {
    "ask": ("general_help", "Ask a software question"),
    "write-code": ("write_code", "Write a function, algorithm or data structure"),
    "new-app": ("new_app", "Build a new app"),
    "review-code": ("review_code", "Review code: findings by severity with fixes"),
    "explain": ("explain_code", "Explain how some code works"),
    "audit": ("analyze_audit", "Audit a project's architecture and quality"),
    "fix-bug": ("fix_bug", "Find and fix a bug"),
    "write-tests": ("write_tests", "Add tests"),
    "write-docs": ("write_docs", "Write documentation"),
    "refactor": ("refactor", "Restructure code without changing behavior"),
    "optimize": ("improve_performance", "Make something faster"),
    "security-review": ("security_review", "Check for security problems"),
    "upgrade": ("upgrade", "Upgrade a framework or dependency"),
    "db-change": ("database_change", "Change the database schema or engine"),
    "add-feature": ("add_feature", "Add a feature to a project"),
    "modernize-ui": ("frontend_modernize", "Modernize a frontend"),
    "dockerize": ("devops_deploy", "Docker, CI/CD and deployment"),
    "translate": ("translate_language", "Rewrite code in another supported language"),
    "change-architecture": ("change_architecture", "Modules, modular monolith, microservices, merge, serverless"),
    "project": ("project_manage", "Project actions: connect, status, deliver"),
}

# The phase in which each intent's playbook is built (Section 15). `general_help` (Answer) is built in Phase 2.
PLAYBOOK_PHASE: dict[str, str] = {
    "general_help": "2",
    "project_manage": "3",
    "explain_code": "6",
    "analyze_audit": "6",
    "write_docs": "6",
    "review_code": "6",
    "write_code": "8",
    "fix_bug": "8",
    "write_tests": "8",
    "refactor": "9",
    "improve_performance": "9",
    "security_review": "10",
    "upgrade": "10",
    "database_change": "10",
    "add_feature": "11",
    "frontend_modernize": "12",
    "new_app": "13",
    "devops_deploy": "14",
    "change_architecture": "15-17",
    "translate_language": "18",
}

INTENT_LABELS: dict[str, str] = {
    "general_help": "Answer",
    "project_manage": "Project ops",
    "explain_code": "Explain",
    "analyze_audit": "Audit",
    "write_docs": "Docs",
    "write_tests": "Tests",
    "fix_bug": "Bug fix",
    "security_review": "Security review",
    "refactor": "Refactor",
    "improve_performance": "Performance",
    "upgrade": "Upgrade",
    "database_change": "Database change",
    "add_feature": "Feature",
    "frontend_modernize": "Frontend",
    "devops_deploy": "DevOps",
    "translate_language": "Translate",
    "change_architecture": "Architecture change",
    "new_app": "New app",
    "write_code": "Write code",
    "review_code": "Code review",
}


@dataclass(frozen=True)
class IntentConfig:
    name: str
    tier: int
    max_tier: int
    lead: str
    playbook: str
    new: bool
    required: tuple[str, ...]
    deliver: str


@cache
def _tiers() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((CONFIG_DIR / "tiers.yaml").read_text(encoding="utf-8"))
    return data


@cache
def _intake() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((CONFIG_DIR / "intake.yaml").read_text(encoding="utf-8"))
    return data


def intent_config(name: str) -> IntentConfig:
    tier = _tiers()["intents"][name]
    intake = _intake()["intents"].get(name, {})
    return IntentConfig(
        name=name,
        tier=int(tier["tier"]),
        max_tier=int(tier.get("max_tier", tier["tier"])),
        lead=tier["lead"],
        playbook=tier["playbook"],
        new=bool(intake.get("new", False)),
        required=tuple(intake.get("required", [])),
        deliver=intake.get("deliver", ""),
    )


def router_settings() -> dict[str, Any]:
    return {**_tiers()["router"], **_tiers()["clarifier"]}


def supported_languages() -> list[str]:
    return list(_intake()["languages"]["supported"])


@dataclass(frozen=True)
class SlashCommand:
    command: str
    intent: Intent
    args: str


_SLASH = re.compile(r"^/([a-z][a-z0-9-]*)(?:\s+(.*))?$", re.DOTALL)


def parse_slash(text: str) -> SlashCommand | None:
    """`/review-code internal/payment` → (review-code, review_code, "internal/payment"). Unknown commands → None."""
    match = _SLASH.match(text.strip())
    if not match or match.group(1) not in SLASH_COMMANDS:
        return None
    return SlashCommand(match.group(1), SLASH_COMMANDS[match.group(1)][0], (match.group(2) or "").strip())


# A language the user asks to *use*: "in Java", "using PHP", "with Rust", "Java project", "rewrite ... to Kotlin".
_LANG_ALIASES = {"c sharp": "c#", "csharp": "c#", "dotnet": ".net", "vb": "visual basic", "objc": "objective-c"}


@cache
def _unsupported_pattern() -> re.Pattern[str]:
    names = sorted({*_intake()["languages"]["suggest"], *_LANG_ALIASES}, key=len, reverse=True)
    alternatives = "|".join(re.escape(n) for n in names)
    # The language must be used as the language of the work, not just mentioned ("what is Java?" is a question).
    return re.compile(
        rf"(?:\b(?:in|using|with|into|to|on)\s+(?:a\s+|an\s+|my\s+)?({alternatives})(?![\w#+])"
        rf"|(?<![\w.#])({alternatives})\s+(?:project|code|app|application|codebase|service|api|backend|version))",
        re.IGNORECASE,
    )


@dataclass(frozen=True)
class LanguageDecline:
    language: str
    suggestions: list[str]

    @property
    def message(self) -> str:
        name = {"c#": "C#", ".net": ".NET", "php": "PHP"}.get(self.language, self.language.title())
        others = [lang for lang in supported_languages() if lang not in self.suggestions]
        options = ", ".join(self.suggestions + others[: max(0, 3 - len(self.suggestions))])
        return (
            f"{name} isn't supported: Codewright works in Python, TypeScript, JavaScript, Go and C++. "
            f"I can do it in {options} (closest first). Which one would you like?"
        )


def unsupported_language(text: str) -> LanguageDecline | None:
    """The first unsupported language the request asks to work in, with the closest supported ones (C12)."""
    match = _unsupported_pattern().search(text)
    if not match:
        return None
    raw = (match.group(1) or match.group(2)).lower()
    name = _LANG_ALIASES.get(raw, raw)
    return LanguageDecline(name, suggestions_for(name))


def suggestions_for(language: str) -> list[str]:
    """The closest supported languages to an unsupported one ("Java" → Go, TypeScript)."""
    key = _LANG_ALIASES.get(language.lower(), language.lower())
    return list(_intake()["languages"]["suggest"].get(key, ["TypeScript", "Python"]))


_SUPPORTED_ALIASES = {
    "python": "Python",
    "py": "Python",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "node": "JavaScript",
    "golang": "Go",
    "go": "Go",
    "c++": "C++",
    "cpp": "C++",
}
_SUPPORTED_PATTERN = re.compile(
    r"(?<![\w+#])(python|py|typescript|ts|javascript|js|node|golang|go|c\+\+|cpp)(?![\w+#])", re.IGNORECASE
)


def named_language(text: str) -> str | None:
    """A supported language the user named ("in Go", "C++, both", "python"), else None.

    "go" is only a language when it isn't the verb ("go ahead", "let's go"): it must follow in/using/with or stand
    alone / at the start of an answer.
    """
    for match in _SUPPORTED_PATTERN.finditer(text):
        word = match.group(1).lower()
        if word == "go":
            before = text[: match.start()].rstrip().lower()
            after = text[match.end() :].lstrip().lower()
            if not (
                before.endswith(("in", "using", "with", "to", "into"))
                or (before == "" and (after == "" or after[:1] in ",.;!" or after.startswith(("and", "lang"))))
                or after.startswith(("lang", "project", "code"))
            ):
                continue
        return _SUPPORTED_ALIASES[word]
    return None
