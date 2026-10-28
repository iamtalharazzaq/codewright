"""Language Packs (CODEWRIGHT.md Section 8.3): exactly five (C12): python, go, typescript, javascript, cpp.

`detect_project` finds every component of a project (mixed projects are fine: each part uses its pack);
`unsupported_project` declines a project written in another language, with the closest supported ones.
"""

from __future__ import annotations

from pathlib import Path

from agent.chat.intents import suggestions_for  # the same suggestions the chat uses (config/intake.yaml)
from agent.language_packs.base import Component, LanguagePack
from agent.language_packs.cpp import CppPack
from agent.language_packs.go import GoPack
from agent.language_packs.node import NodePack
from agent.language_packs.python import PythonPack

PACKS: dict[str, LanguagePack] = {
    p.name: p for p in (PythonPack(), GoPack(), NodePack(typescript=True), NodePack(typescript=False), CppPack())
}
SUPPORTED = ("Python", "Go", "TypeScript", "JavaScript", "C++")


def pack(name: str) -> LanguagePack:
    try:
        return PACKS[name]
    except KeyError:
        raise KeyError(f"no Language Pack {name!r}; the five are {', '.join(PACKS)}") from None


def detect_project(repo: Path) -> list[Component]:
    """Every buildable component, root first, then by path."""
    found = [c for p in PACKS.values() for c in p.detect(repo)]
    return sorted(found, key=lambda c: (c.path != ".", c.path, c.pack))


def unsupported_project(languages: dict[str, int], min_share: float = 0.5) -> tuple[str, list[str]] | None:
    """(language, closest supported) when a project is mostly an unsupported language and has no supported part
    worth working on; None otherwise. `languages`: file counts per language (Workspace.summary)."""
    code = {k: v for k, v in languages.items() if k not in {"SQL", "C/C++"}}
    total = sum(code.values())
    if not total:
        return None
    top, count = max(code.items(), key=lambda kv: kv[1])
    supported = sum(v for k, v in code.items() if k in SUPPORTED)
    if top in SUPPORTED or count / total < min_share or supported / total >= 0.25:
        return None
    return top, suggestions_for(top)


__all__ = ["PACKS", "SUPPORTED", "Component", "LanguagePack", "detect_project", "pack", "unsupported_project"]
