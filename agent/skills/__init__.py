"""Skill Registry (CODEWRIGHT.md Section 8.6, ADR 0021): loader, validator, matcher, import/export.

A skill is a folder with a `SKILL.md` (YAML frontmatter + Markdown instructions). Three places, in this order:
- `skills/builtin/` (read-only, one per playbook / slash command),
- `skills/user/` (global custom skills),
- `workspaces/<project>/skills/` (project-scoped custom skills).

Skills never bypass the confirm card, gates, guardrails, the sandbox or the 5-language rule: they only pick an
intent and add instructions to it. Imported skills are untrusted: validated, secret-scanned and saved disabled.
"""

from __future__ import annotations

import io
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from agent.chat.intents import INTENT_LABELS, Intent
from agent.tools.secrets import scan_text
from connectors.inputs import ZipLimits, extract_zip

ROOT = Path(__file__).resolve().parents[2]
BUILTIN_DIR = ROOT / "skills" / "builtin"
SKILL_FILE = "SKILL.md"
MAX_SKILL_BYTES = 64_000
MAX_FILES_PER_SKILL = 20
MAX_IMPORT_SKILLS = 50

Language = Literal["python", "go", "typescript", "javascript", "cpp"]
# What a skill may ask for (Section 8.6 "allowed_tools"); playbooks only grant what their own agents may use anyway.
Tool = Literal[
    "read_files", "graph_query", "code_search", "run_linters", "run_tests", "run_app", "write_files", "web_preview"
]  # fmt: skip
TOOLS: tuple[str, ...] = Tool.__args__  # type: ignore[attr-defined]
LANGUAGES: tuple[str, ...] = Language.__args__  # type: ignore[attr-defined]
Source = Literal["builtin", "user", "project"]

_NAME = re.compile(r"^[a-z][a-z0-9-]{1,48}$")
_COMMAND = re.compile(r"^/[a-z][a-z0-9-]{1,40}$")
_SCOPE = re.compile(r"^(global|project:[0-9a-f-]{36})$")
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_WORD = re.compile(r"[a-z][a-z0-9+#]{2,}")
_STOP = {
    "the", "and", "for", "with", "this", "that", "use", "when", "user", "asks", "code", "can", "you", "please", "from",
    "into", "are", "our", "your", "all", "any", "one", "two", "how", "what", "who", "why", "make", "want", "need",
    "does", "check", "run", "skill", "using", "about", "give", "show", "some", "its", "it's", "has", "have", "will",
}  # fmt: skip


class SkillError(ValueError):
    """A skill that can't be saved or imported. `problems` lists every reason, for the UI."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class SkillInput(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    required: bool = False
    description: str = Field(default="", max_length=200)


class SkillMeta(BaseModel):
    """The frontmatter. `playbook` is the intent that runs the skill (e.g. `review_code`) or `custom` (a chat
    answer that follows the instructions)."""

    name: str
    command: str
    title: str = ""
    description: str = Field(min_length=10, max_length=500)
    languages: list[Language] = Field(default_factory=list)
    scope: str = "global"
    playbook: Intent | Literal["custom"] = "custom"
    tier: int = Field(default=0, ge=0, le=3)
    inputs: list[SkillInput] = Field(default_factory=list, max_length=5)
    allowed_tools: list[Tool] = Field(default_factory=list)
    output: str = Field(default="markdown", max_length=60)
    enabled: bool = True
    auto_use: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _NAME.match(v):
            raise ValueError("name: lowercase letters, digits and dashes, 2-49 characters (e.g. go-style-review)")
        return v

    @field_validator("command")
    @classmethod
    def _command(cls, v: str) -> str:
        v = v if v.startswith("/") else f"/{v}"
        if not _COMMAND.match(v):
            raise ValueError("command: a slash and lowercase letters, digits or dashes (e.g. /go-style-review)")
        return v

    @field_validator("scope")
    @classmethod
    def _scope(cls, v: str) -> str:
        if not _SCOPE.match(v):
            raise ValueError("scope: 'global' or 'project:<project id>'")
        return v

    @field_validator("languages", "allowed_tools")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))

    @property
    def display(self) -> str:
        return self.title or self.name.replace("-", " ").capitalize()


@dataclass(frozen=True)
class Skill:
    meta: SkillMeta
    instructions: str
    source: Source
    path: Path | None = None  # the skill's folder
    files: tuple[str, ...] = ()  # other files in the folder (examples, templates)

    @property
    def name(self) -> str:
        return self.meta.name

    @property
    def intent(self) -> str | None:
        return None if self.meta.playbook == "custom" else self.meta.playbook

    @property
    def project_id(self) -> str | None:
        return self.meta.scope.removeprefix("project:") if self.meta.scope != "global" else None

    @property
    def editable(self) -> bool:
        return self.source != "builtin"

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.meta.model_dump(),
            "title": self.meta.display,
            "instructions": self.instructions,
            "source": self.source,
            "editable": self.editable,
            "files": list(self.files),
            "markdown": render(self.meta, self.instructions),
        }

    def summary(self) -> dict[str, str]:
        return {"name": self.name, "title": self.meta.display, "command": self.meta.command, "source": self.source}


# ── SKILL.md ─────────────────────────────────────────────────────────────────
def parse(text: str, *, source: Source = "user", path: Path | None = None) -> Skill:
    """`SKILL.md` text → Skill. Raises SkillError with every problem found."""
    if len(text.encode("utf-8")) > MAX_SKILL_BYTES:
        raise SkillError([f"SKILL.md is larger than {MAX_SKILL_BYTES // 1000} KB"])
    match = _FRONTMATTER.match(text.lstrip("﻿"))
    if not match:
        raise SkillError(["SKILL.md must start with YAML frontmatter between two '---' lines"])
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillError([f"frontmatter is not valid YAML: {exc}"]) from None
    if not isinstance(data, dict):
        raise SkillError(["frontmatter must be a YAML mapping (key: value lines)"])
    try:
        meta = SkillMeta.model_validate(data)
    except ValidationError as exc:
        raise SkillError([_problem(e) for e in exc.errors()]) from None
    instructions = match.group(2).strip()
    if not instructions:
        raise SkillError(["the instructions (the Markdown after the frontmatter) are empty"])
    files: tuple[str, ...] = ()
    if path is not None:
        files = tuple(sorted(str(p.relative_to(path)) for p in path.rglob("*") if p.is_file() and p.name != SKILL_FILE))
    return Skill(meta, instructions, source, path, files)


def _problem(error: Any) -> str:
    loc = ".".join(str(x) for x in error.get("loc", ())) or "frontmatter"
    msg = str(error.get("msg", "invalid")).removeprefix("Value error, ")
    return msg if msg.startswith(f"{loc}:") else f"{loc}: {msg}"


def render(meta: SkillMeta, instructions: str) -> str:
    data = meta.model_dump(exclude_defaults=False)
    if not data["title"]:
        data.pop("title")
    if not data["inputs"]:
        data.pop("inputs")
    front = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120).strip()
    return f"---\n{front}\n---\n\n{instructions.strip()}\n"


def secrets_in(text: str) -> list[str]:
    return [f"line {f.line}: looks like a {f.kind}" for f in scan_text(text)]


# ── matching ─────────────────────────────────────────────────────────────────
def keywords(text: str) -> set[str]:
    words = {w.rstrip("s") if len(w) > 4 else w for w in _WORD.findall(text.lower().replace("-", " "))}
    return {w for w in words if w not in _STOP}


def keyword_score(skill: Skill, message: str) -> float:
    """Share of the skill's own name/title words found in the message, plus description overlap (0-1)."""
    asked = keywords(message)
    if not asked:
        return 0.0
    head = keywords(f"{skill.meta.name} {skill.meta.title} {skill.meta.command}")
    body = keywords(skill.meta.description) - head
    head_hit = len(head & asked) / len(head) if head else 0.0
    body_hit = len(body & asked) / min(len(asked), 6) if body else 0.0
    return round(min(1.0, 0.7 * head_hit + 0.5 * body_hit), 3)


# ── the registry ─────────────────────────────────────────────────────────────
class SkillRegistry:
    def __init__(self, user_dir: Path, workspaces_dir: Path, builtin_dir: Path = BUILTIN_DIR) -> None:
        self.builtin_dir = builtin_dir
        self.user_dir = user_dir
        self.workspaces_dir = workspaces_dir

    def _project_dir(self, project_id: str) -> Path:
        return self.workspaces_dir / project_id / "skills"

    def _dir_for(self, meta: SkillMeta) -> Path:
        pid = meta.scope.removeprefix("project:") if meta.scope != "global" else None
        return (self._project_dir(pid) if pid else self.user_dir) / meta.name

    @staticmethod
    def _load_dir(root: Path, source: Source) -> list[Skill]:
        skills: list[Skill] = []
        if not root.is_dir():
            return skills
        for folder in sorted(p for p in root.iterdir() if (p / SKILL_FILE).is_file()):
            try:
                skills.append(parse((folder / SKILL_FILE).read_text(encoding="utf-8"), source=source, path=folder))
            except (SkillError, OSError, UnicodeDecodeError):
                continue  # a broken file never takes the registry down; the Skills screen can't list it
        return skills

    def builtins(self) -> list[Skill]:
        return self._load_dir(self.builtin_dir, "builtin")

    def all(self, project_id: str | None = None) -> list[Skill]:
        skills = self.builtins() + self._load_dir(self.user_dir, "user")
        if project_id:
            skills += self._load_dir(self._project_dir(project_id), "project")
        return skills

    def enabled(self, project_id: str | None = None) -> list[Skill]:
        return [s for s in self.all(project_id) if s.meta.enabled]

    def get(self, name: str, project_id: str | None = None) -> Skill:
        for skill in reversed(self.all(project_id)):  # project before user before builtin
            if skill.name == name:
                return skill
        raise LookupError(f"No skill named {name!r}")

    def by_command(
        self, command: str, project_id: str | None = None, *, include_disabled: bool = False
    ) -> Skill | None:
        command = command if command.startswith("/") else f"/{command}"
        for skill in reversed(self.all(project_id)):
            if skill.meta.command == command and (include_disabled or skill.meta.enabled):
                return skill
        return None

    def custom_for_matching(self, project_id: str | None, language: str | None = None) -> list[Skill]:
        """Custom skills that may be picked automatically for this chat."""
        return [
            s
            for s in self.enabled(project_id)
            if s.source != "builtin"
            and s.meta.auto_use
            and (not language or not s.meta.languages or language in s.meta.languages)
        ]

    # ── writing ──────────────────────────────────────────────────────────────
    def validate(self, skill: Skill, *, replacing: str | None = None) -> None:
        problems: list[str] = []
        builtin = {s.name: s for s in self.builtins()}
        if skill.name in builtin:
            problems.append(f"name: {skill.name!r} is a built-in skill; pick another name")
        if any(s.meta.command == skill.meta.command for s in builtin.values()):
            problems.append(f"command: {skill.meta.command} is a built-in command; pick another")
        mine = (skill.name, replacing)
        others = [s for s in self.all(skill.project_id) if s.source != "builtin" and s.name not in mine]
        if any(s.meta.command == skill.meta.command for s in others):
            problems.append(f"command: {skill.meta.command} is already used by another skill")
        problems += [f"secret found ({p}); remove it" for p in secrets_in(render(skill.meta, skill.instructions))]
        if problems:
            raise SkillError(problems)

    def save(self, markdown: str, *, replacing: str | None = None, enabled: bool | None = None) -> Skill:
        """Create or replace a custom skill from its SKILL.md text. `replacing` is the old name when renaming."""
        skill = parse(markdown)
        if enabled is not None:
            skill = Skill(skill.meta.model_copy(update={"enabled": enabled}), skill.instructions, skill.source)
        self.validate(skill, replacing=replacing)
        folder = self._dir_for(skill.meta)
        if replacing is None and (folder / SKILL_FILE).exists():
            raise SkillError([f"name: a skill named {skill.name!r} already exists"])
        if replacing and replacing != skill.name:
            old = self.get(replacing, skill.project_id)
            if old.source == "builtin":
                raise SkillError(["built-in skills can't be changed"])
            if old.path:
                shutil.move(str(old.path), str(folder))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / SKILL_FILE).write_text(render(skill.meta, skill.instructions), encoding="utf-8")
        return self.get(skill.name, skill.project_id)

    def set_flags(self, name: str, project_id: str | None, **flags: bool) -> Skill:
        skill = self.get(name, project_id)
        if not skill.editable or skill.path is None:
            raise SkillError(["built-in skills can't be changed"])
        meta = skill.meta.model_copy(update=flags)
        (skill.path / SKILL_FILE).write_text(render(meta, skill.instructions), encoding="utf-8")
        return self.get(name, project_id)

    def delete(self, name: str, project_id: str | None = None) -> None:
        skill = self.get(name, project_id)
        if not skill.editable or skill.path is None:
            raise SkillError(["built-in skills can't be deleted"])
        shutil.rmtree(skill.path)

    # ── import / export ──────────────────────────────────────────────────────
    def export_zip(self, names: list[str], project_id: str | None = None) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in names:
                skill = self.get(name, project_id)
                zf.writestr(f"{skill.name}/{SKILL_FILE}", render(skill.meta, skill.instructions))
                if skill.path:
                    for rel in skill.files:
                        zf.write(skill.path / rel, f"{skill.name}/{rel}")
        return buf.getvalue()

    def import_tree(self, tree: Path, *, project_id: str | None = None) -> list[dict[str, Any]]:
        """Import every skill folder under `tree` (an extracted ZIP, a folder or a clone).

        Each one is validated and secret-scanned; good ones are saved **disabled** (Section 8.6: untrusted until the
        user enables them; only enabled skills are ever auto-used), into the global or the given project scope.
        Returns one result per skill found, for the preview."""
        results: list[dict[str, Any]] = []
        folders = sorted({p.parent for p in tree.rglob(SKILL_FILE) if p.is_file() and not p.is_symlink()})
        if not folders:
            raise SkillError([f"no {SKILL_FILE} found"])
        for folder in folders[:MAX_IMPORT_SKILLS]:
            rel = str(folder.relative_to(tree)) or "."
            try:
                results.append({"folder": rel, "ok": True, **self._import_one(folder, project_id)})
            except SkillError as exc:
                results.append({"folder": rel, "ok": False, "problems": exc.problems})
            except (OSError, UnicodeDecodeError) as exc:
                results.append({"folder": rel, "ok": False, "problems": [f"unreadable: {exc}"]})
        return results

    def _import_one(self, folder: Path, project_id: str | None) -> dict[str, Any]:
        extra = [p for p in folder.rglob("*") if p.is_file() and p.name != SKILL_FILE]
        if any(p.is_symlink() for p in folder.rglob("*")):
            raise SkillError(["the skill folder contains symlinks"])
        if len(extra) > MAX_FILES_PER_SKILL:
            raise SkillError([f"more than {MAX_FILES_PER_SKILL} extra files"])
        text = (folder / SKILL_FILE).read_text(encoding="utf-8")
        skill = parse(text, source="user")
        scope = f"project:{project_id}" if project_id else "global"
        meta = skill.meta.model_copy(update={"scope": scope, "enabled": False})
        problems: list[str] = []
        for p in extra:
            if p.stat().st_size > MAX_SKILL_BYTES:
                problems.append(f"{p.relative_to(folder)}: larger than {MAX_SKILL_BYTES // 1000} KB")
                continue
            with_secrets = secrets_in(p.read_text(encoding="utf-8", errors="replace"))
            problems += [f"{p.relative_to(folder)} {s}: secret found" for s in with_secrets]
        if problems:
            raise SkillError(problems)
        replaced = None
        try:
            existing = self.get(meta.name, project_id)
            if existing.source != "builtin":
                replaced = existing.name
        except LookupError:
            pass
        saved = self.save(render(meta, skill.instructions), replacing=replaced)
        if saved.path:
            for p in extra:
                dest = saved.path / p.relative_to(folder)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dest)
        return {
            "name": saved.name,
            "command": saved.meta.command,
            "description": saved.meta.description,
            "allowed_tools": saved.meta.allowed_tools,
            "playbook": saved.meta.playbook,
            "instructions_preview": saved.instructions[:1500],
            "replaced": replaced is not None,
            "enabled": False,
        }

    def import_zip(self, archive: Path, *, project_id: str | None = None) -> list[dict[str, Any]]:
        with tempfile.TemporaryDirectory() as tmp:
            root = extract_zip(
                archive,
                Path(tmp) / "x",
                ZipLimits(max_files=500, max_total_bytes=5_000_000, max_file_bytes=MAX_SKILL_BYTES),
            )
            return self.import_tree(root, project_id=project_id)


def intent_label(skill: Skill) -> str:
    return INTENT_LABELS.get(skill.meta.playbook, "Custom")
