"""Skills (Phase 6 task 6): built-ins, custom skills, import/export, matching, drafting from a chat, corrections."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import get_args

import pytest

from agent.chat import corrections, skill_draft
from agent.chat.intents import Intent
from agent.skills import SkillError, SkillRegistry, keyword_score, parse
from agent.tests.playbooks.helpers import llm_returning

NOTES = """---
name: release-notes
command: /release-notes
title: Release notes
description: Turn a list of commits into release notes with Added, Changed and Fixed sections.
---

## Instructions
1. Sort the commits into Added, Changed and Fixed.
2. One short past-tense line each; breaking changes first, in bold.
"""


@pytest.fixture
def registry(tmp_path: Path) -> SkillRegistry:
    return SkillRegistry(tmp_path / "user", tmp_path / "workspaces")


def test_every_built_in_skill_parses_and_runs_a_known_playbook(registry: SkillRegistry) -> None:
    builtins = registry.builtins()
    assert len(builtins) == len(list((Path(__file__).parents[2] / "skills" / "builtin").iterdir()))
    for skill in builtins:
        assert skill.meta.command == f"/{skill.name}"
        assert skill.meta.playbook == "custom" or skill.meta.playbook in get_args(Intent), skill.name
    assert {s.name for s in builtins} >= {"review-code", "audit", "docs", "explain", "create-skill"}


def test_save_get_flags_and_delete_a_custom_skill(registry: SkillRegistry) -> None:
    saved = registry.save(NOTES)
    assert saved.source == "user" and saved.meta.enabled and saved.meta.auto_use
    assert registry.by_command("/release-notes") is not None
    registry.set_flags("release-notes", None, enabled=False)
    assert registry.by_command("/release-notes") is None
    assert registry.by_command("/release-notes", include_disabled=True) is not None
    registry.delete("release-notes")
    with pytest.raises(LookupError):
        registry.get("release-notes")


def test_problems_are_reported_not_saved(registry: SkillRegistry) -> None:
    with pytest.raises(SkillError) as built_in:
        registry.save(NOTES.replace("release-notes", "review-code"))
    assert any("built-in" in p for p in built_in.value.problems)
    with pytest.raises(SkillError) as secret:
        registry.save(NOTES + '\nUse token = "ghp_' + "a" * 36 + '"\n')
    assert any("secret" in p for p in secret.value.problems)
    with pytest.raises(SkillError):
        parse("---\nname: X Y\ncommand: nope\ndescription: short\n---\n")
    registry.save(NOTES)
    with pytest.raises(SkillError, match="already"):
        registry.save(NOTES.replace("name: release-notes", "name: notes-two"))  # same command


def test_export_then_import_arrives_disabled_with_its_settings(registry: SkillRegistry, tmp_path: Path) -> None:
    registry.save(NOTES)
    archive = tmp_path / "notes.zip"
    archive.write_bytes(registry.export_zip(["release-notes"]))
    assert zipfile.ZipFile(archive).namelist() == ["release-notes/SKILL.md"]
    registry.delete("release-notes")

    results = registry.import_zip(archive)
    assert results[0]["ok"] and results[0]["name"] == "release-notes"
    imported = registry.get("release-notes")
    assert not imported.meta.enabled  # untrusted until the user enables it
    assert imported.meta.auto_use  # its own setting is kept: it applies once enabled
    assert registry.custom_for_matching(None) == []
    registry.set_flags("release-notes", None, enabled=True)
    assert [s.name for s in registry.custom_for_matching(None)] == ["release-notes"]


def test_an_import_with_a_secret_in_an_extra_file_is_refused(registry: SkillRegistry, tmp_path: Path) -> None:
    tree = tmp_path / "tree" / "release-notes"
    tree.mkdir(parents=True)
    (tree / "SKILL.md").write_text(NOTES, encoding="utf-8")
    (tree / "example.env").write_text("AWS_KEY=AKIA" + "A" * 16 + "\n", encoding="utf-8")
    results = registry.import_tree(tmp_path / "tree")
    assert not results[0]["ok"] and "secret" in results[0]["problems"][0]


def test_matching_by_keywords_and_language(registry: SkillRegistry) -> None:
    skill = registry.save(NOTES)
    assert keyword_score(skill, "write release notes for these commits") >= 0.6
    assert keyword_score(skill, "how do I reverse a string in Go?") < 0.15
    registry.save(NOTES.replace("release-notes", "go-notes").replace("---\n\n", "languages: [go]\n---\n\n", 1))
    assert {s.name for s in registry.custom_for_matching(None, "python")} == {"release-notes"}
    assert {s.name for s in registry.custom_for_matching(None, "go")} == {"release-notes", "go-notes"}


async def test_a_draft_keeps_only_the_languages_the_user_named() -> None:
    reply = {
        "name": "Release Notes",
        "title": "Release notes",
        "description": "Release notes from a list of commits.",
        "playbook": "custom",
        "languages": ["python", "go"],
        "steps": ["Sort the commits", "Write one line each"],
        "output_format": "Markdown with three sections.",
    }
    client, _ = llm_returning(reply)
    history = [{"role": "user", "content": "Release notes for my Go service, please"}]
    skill = parse(await skill_draft.draft(client, "", history))
    assert skill.name == "release-notes" and skill.meta.languages == ["go"]
    assert "1. Sort the commits" in skill.instructions


def test_save_this_as_a_skill_is_recognized() -> None:
    for text in ("save this as a skill", "Turn that into a skill", "make it into my new skill"):
        assert skill_draft.SAVE_AS_SKILL.search(text), text
    assert not skill_draft.SAVE_AS_SKILL.search("what is a skill?")


async def test_a_correction_becomes_facts_on_known_modules() -> None:
    modules = ["internal/billing", "internal/mailer", "web"]
    assert corrections.looks_like_correction("That's wrong, billing also calls mailer")
    assert not corrections.looks_like_correction("How does billing work?")
    assert corrections.match_module("Billing service", modules) == "internal/billing"
    assert corrections.match_module("payments", modules) is None
    client, _ = llm_returning(
        {"facts": [{"source": "billing", "target": "mailer", "relation": "calls", "note": "also calls"},
                   {"source": "billing", "target": "ledger", "relation": "calls", "note": ""}]}
    )  # fmt: skip
    facts = await corrections.parse(client, "That's wrong, billing also calls mailer and ledger", modules)
    assert facts == [
        {"source": "internal/billing", "target": "internal/mailer", "relation": "calls", "note": "also calls"}
    ]
    assert corrections.describe(facts[0]) == "internal/billing calls internal/mailer"
