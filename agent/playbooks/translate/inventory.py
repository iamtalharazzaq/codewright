"""The units of a program to translate (CODEWRIGHT.md Section 5.16, "one function at a time"): found by rules, not by a
model. A unit is a top-level function, class/type, constant block or the program's entry point, with its source,
what it calls, and the order to translate in (callees first, so each unit sees the names it uses).

Python is parsed with `ast`. The other four languages use declaration patterns and brace matching: good for
ordinary code, approximate for unusual layouts, so `coverage` says how much of the source the units hold and the
report shows it.
"""

from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent.tools.secrets import SKIP_DIRS

SUFFIXES = {
    "Python": (".py",),
    "Go": (".go",),
    "TypeScript": (".ts", ".tsx"),
    "JavaScript": (".js", ".mjs", ".jsx"),
    "C++": (".cpp", ".cc", ".cxx", ".hpp", ".h"),
}
TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test|[^/]*\.test|[^/]*\.spec|tests?)(\.|/)", re.IGNORECASE)
MAX_UNIT_CHARS = 6000  # a unit longer than this does not fit a small model's context in one go
IGNORED_LINE = re.compile(r"^\s*(#|//|/\*|\*|$)")


@dataclass
class Unit:
    id: str  # file::name
    name: str
    kind: str  # function, class, const, entry
    file: str  # relative to the project root
    start: int
    end: int
    source: str
    calls: list[str] = field(default_factory=list)  # ids of the units this one uses
    entry: bool = False
    too_long: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def lines(self) -> int:
        return self.end - self.start + 1


def source_files(work: Path, component_path: str, language: str) -> list[str]:
    """The component's source files (tests and generated/vendored folders left out), as paths from the root."""
    root = work / component_path if component_path != "." else work
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in SUFFIXES[language]:
            continue
        rel = path.relative_to(work).as_posix()
        if any(part in SKIP_DIRS for part in path.relative_to(work).parts) or TEST_FILE.search(rel):
            continue
        found.append(rel)
    return found


# ── Python ───────────────────────────────────────────────────────────────────
def _py_units(file: str, text: str) -> list[Unit]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    units: list[Unit] = []
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            entry = node.name == "main"
            units.append(
                _unit(file, node.name, "entry" if entry else kind, first, node.end_lineno or first, lines, entry)
            )
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            ids = [t.id for t in targets if isinstance(t, ast.Name)]
            if ids:
                units.append(_unit(file, ids[0], "const", node.lineno, node.end_lineno or node.lineno, lines, False))
        elif isinstance(node, ast.If) and _is_main_guard(node):
            if "main" not in names:  # a guard that only calls main() adds nothing; otherwise it is the entry point
                units.append(_unit(file, "__main__", "entry", node.lineno, node.end_lineno or node.lineno, lines, True))
    return units


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and any(isinstance(c, ast.Constant) and c.value == "__main__" for c in test.comparators)
    )


# ── the other four: declaration patterns + brace matching ────────────────────
_STRINGS = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`[^`]*`')
_COMMENT = re.compile(r"//.*$")
PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "Go": [
        ("function", re.compile(r"^func\s+(?:\(\s*\w+\s+\*?(\w+)\s*\)\s*)?(\w+)\s*[(\[]")),
        ("class", re.compile(r"^type\s+(\w+)\s+(?:struct|interface)\b")),
        ("const", re.compile(r"^(?:const|var)\s+(\w+)\b")),
        ("const", re.compile(r"^(?:const|var)\s*\(")),
    ],
    "TypeScript": [
        ("function", re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)")),
        ("class", re.compile(r"^(?:export\s+)?(?:abstract\s+)?(?:class|interface|enum)\s+(\w+)")),
        ("class", re.compile(r"^(?:export\s+)?type\s+(\w+)\s*(?:<[^>]*>)?\s*=")),
        (
            "function",
            re.compile(r"^(?:export\s+)?const\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*(?::[^=]+)?=>"),
        ),
        ("const", re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)")),
    ],
    "C++": [
        ("class", re.compile(r"^(?:template\s*<[^>]*>\s*)?(?:class|struct|enum(?:\s+class)?)\s+(\w+)\b[^;]*$")),
        ("function", re.compile(r"^(?:[\w:<>,\*&~]+\s+)+[\*&]?(\w+(?:::\w+)?)\s*\([^;]*$")),
        ("const", re.compile(r"^(?:static\s+)?(?:constexpr|const)\s+[\w:<>,\*&\s]+\s+(\w+)\s*=")),
    ],
}
PATTERNS["JavaScript"] = PATTERNS["TypeScript"]


def _depth(line: str) -> int:
    text = _COMMENT.sub("", _STRINGS.sub('""', line))
    return sum(text.count(c) for c in "{([") - sum(text.count(c) for c in "})]")


def _block_end(lines: list[str], start: int) -> int:
    """Index of the line where the declaration starting at `start` ends: brace depth back to 0, or a one-liner."""
    depth = 0
    for i in range(start, min(len(lines), start + 800)):
        depth += _depth(lines[i])
        if depth <= 0 and (i > start or lines[i].rstrip().endswith((";", "}", ")", ",")) or "{" not in lines[i]):
            return i
    return min(len(lines), start + 800) - 1


def _braced_units(file: str, text: str, language: str) -> list[Unit]:
    lines = text.splitlines()
    units: list[Unit] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        hit = None
        if line and not line[0].isspace():
            for kind, pattern in PATTERNS[language]:
                if m := pattern.match(line):
                    hit = (kind, m)
                    break
        if hit is None:
            i += 1
            continue
        kind, m = hit
        end = _block_end(lines, i)
        groups = [g for g in m.groups() if g]
        two = language == "Go" and len(groups) == 2
        name = f"{groups[0]}.{groups[1]}" if two else (groups[-1] if groups else "block")
        start = i
        while start > 0 and lines[start - 1].lstrip().startswith(("//", "/*", "*", "@")):  # doc comment / decorators
            start -= 1
        is_entry = name.split("::")[-1] == "main" and kind == "function"
        units.append(_unit(file, name, "entry" if is_entry else kind, start + 1, end + 1, lines, is_entry))
        i = end + 1
    return units


def _unit(file: str, name: str, kind: str, start: int, end: int, lines: list[str], entry: bool) -> Unit:
    source = "\n".join(lines[start - 1 : end])
    too_long = len(source) > MAX_UNIT_CHARS
    return Unit(f"{file}::{name}", name, kind, file, start, end, source, entry=entry, too_long=too_long)


# ── the whole component ──────────────────────────────────────────────────────
def scan(work: Path, component_path: str, language: str) -> list[Unit]:
    """Every unit of the component, in translation order (a unit's dependencies come before it, entry point last)."""
    units: list[Unit] = []
    for file in source_files(work, component_path, language):
        text = (work / file).read_text(encoding="utf-8", errors="replace")
        units += _py_units(file, text) if language == "Python" else _braced_units(file, text, language)
    _link(units)
    return order(units)


def _link(units: list[Unit]) -> None:
    by_name: dict[str, Unit] = {}
    for u in units:
        by_name.setdefault(u.name.split(".")[0].split("::")[0], u)
    for u in units:
        words = set(re.findall(r"[A-Za-z_]\w*", u.source))
        u.calls = [by_name[w].id for w in sorted(words) if w in by_name and by_name[w].id != u.id]


def order(units: list[Unit]) -> list[Unit]:
    """Callees first (depth-first over the calls, source order for ties); the entry point is always last."""
    index = {u.id: u for u in units}
    done: list[Unit] = []
    seen: set[str] = set()

    def visit(u: Unit) -> None:
        if u.id in seen:
            return
        seen.add(u.id)  # a cycle stops here: the unit goes in source order
        for dep in u.calls:
            visit(index[dep])
        done.append(u)

    for u in sorted((u for u in units if not u.entry), key=lambda u: (u.file, u.start)):
        visit(u)
    for u in (u for u in units if u.entry):
        visit(u)
    return [*(u for u in done if not u.entry), *(u for u in done if u.entry)]


def coverage(work: Path, units: list[Unit], files: list[str]) -> float:
    """The share of the source's code lines that belong to a unit (the rest is imports and loose statements)."""
    total = held = 0
    for file in files:
        lines = (work / file).read_text(encoding="utf-8", errors="replace").splitlines()
        inside = {n for u in units if u.file == file for n in range(u.start, u.end + 1)}
        for n, line in enumerate(lines, 1):
            if IGNORED_LINE.match(line) or re.match(r"^\s*(import|from|using|#include|package)\b", line):
                continue
            total += 1
            held += n in inside
    return round(held / total, 2) if total else 1.0
