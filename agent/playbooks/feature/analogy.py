"""Feature by analogy (CODEWRIGHT.md Section 5.13): most features an app gains look like one it already has (price
alerts like the wishlist, coupons like discounts). The files of that existing feature, across every layer, are the
plan: each one becomes a new file adapted from it, and every file that wires the existing feature in gets the new one
wired in next to it. The model only has to pick the analog and name the new feature, an answer a small model gives
reliably; guessing a whole layered file layout is not.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from agent.playbooks.change_core import SOURCE_BUDGET, PlannedStep
from agent.playbooks.review_core import TEST_FILE

CODE = {".go", ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".java", ".kt", ".cs", ".rb", ".php", ".cpp", ".h", ".hpp"}
SKIP = {"node_modules", "vendor", ".venv", "venv", "dist", "build", "target", "__pycache__", ".git", "migrations"}
ROLE_SUFFIXES = (
    "handlers", "handler", "service", "services", "repository", "repo", "controller", "routes", "router", "model",
    "models", "store", "api", "test", "spec", "page", "view", "component", "schema", "dto",
)  # fmt: skip
GENERIC = {
    "main", "index", "errors", "error", "converters", "utils", "util", "helpers", "helper", "client", "server",
    "config", "types", "init", "app", "base", "common", "constants", "middleware", "logger", "db", "mocks", "doc",
    *ROLE_SUFFIXES,
}  # fmt: skip
MIN_DIRS = 3  # a feature spans layers: its stem appears in at least this many folders
MAX_ANALOG_FILES = 14
MAX_WIRING = 6
MAX_BLOCK = 1500  # characters of the analog's declarations an append is adapted from


def snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).replace("-", "_").lower()


def pascal(name: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in snake(name).split("_") if p)


def camel(name: str) -> str:
    p = pascal(name)
    return p[:1].lower() + p[1:]


def stem_of(path: str) -> str:
    """`internal/user/port/http/wishlist_handlers_test.go`, `test_wishlist.py` and `mocks/WishlistRepository.go` are
    all `wishlist`."""
    name = snake(Path(path).name.split(".")[0]).removeprefix("test_")
    changed = True
    while changed:
        changed = False
        for suffix in ROLE_SUFFIXES:
            for sep in ("_", "."):
                if name.endswith(sep + suffix) and len(name) > len(suffix) + 1:
                    name, changed = name[: -len(suffix) - 1], True
    return name


def _files(work: Path) -> list[str]:
    out: list[str] = []
    for root, dirs, files in os.walk(work):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
        rel = Path(root).relative_to(work)
        out += [(rel / f).as_posix().removeprefix("./") for f in files if Path(f).suffix in CODE]
    return sorted(out)


def features(work: Path) -> dict[str, list[str]]:
    """Existing features: stems whose files sit in at least MIN_DIRS folders, with those files."""
    by_stem: dict[str, list[str]] = defaultdict(list)
    for f in _files(work):
        by_stem[stem_of(f)].append(f)
    return {
        s: files
        for s, files in sorted(by_stem.items())
        if len(s) > 2 and s not in GENERIC and len({str(Path(f).parent) for f in files}) >= MIN_DIRS
    }


def rename(path: str, analog: str, name: str) -> str:
    """The analog file's path for the new feature: the stem in each spelling it is written in (`wishlist`,
    `Wishlist`, `wishList`) replaced by the new one."""
    p = Path(path)
    base = p.name
    spellings = [(pascal(analog), pascal(name)), (snake(analog), snake(name))]
    if camel(analog) != snake(analog):  # a one-word stem reads the same in both; snake_case files keep snake_case
        spellings.insert(1, (camel(analog), camel(name)))
    for old, new in spellings:
        base = base.replace(old, new)
    return (p.parent / base).as_posix().removeprefix("./")


def wiring(work: Path, analog: str, own: set[str]) -> list[str]:
    """Files outside the analog's own that mention it: where it is registered (routes, containers, converters)."""
    words = re.compile(rf"\b({re.escape(pascal(analog))}|{re.escape(camel(analog))}|{re.escape(snake(analog))})", re.I)
    found = []
    for f in _files(work):
        if f in own or TEST_FILE.search(f):
            continue
        try:
            text = (work / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if words.search(text):
            found.append(f)
    return found


GENERATED = re.compile(r"code generated|do not edit|@generated", re.I)


@dataclass
class AnalogPlan:
    steps: list[PlannedStep] = field(default_factory=list)
    templates: dict[str, str] = field(default_factory=dict)  # new file → the analog file it is adapted from
    appends: dict[str, str] = field(default_factory=dict)  # long file → the analog's declarations to add a copy of
    left_out: list[str] = field(default_factory=list)


def declared_blocks(text: str, analog: str) -> str:
    """The top-level type declarations of the analog in a file (`export interface WishlistItem { ... }`,
    `type Wishlist struct`), each from its first line to its closing brace."""
    head = re.compile(
        rf"^(?:export\s+)?(?:interface|type|class|struct|enum)\s+\w*{pascal(analog)}\w*"  # top-level types only
    )
    lines = text.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        if head.match(lines[i]):
            j = i
            if lines[i].rstrip().endswith("{"):
                while j + 1 < len(lines) and j - i < 30 and not lines[j].startswith("}"):
                    j += 1
            blocks.append("\n".join(lines[i : j + 1]))
            i = j
        i += 1
    return "\n\n".join(blocks)[:MAX_BLOCK]


def plan(work: Path, analog: str, name: str, request: str, files: list[str]) -> AnalogPlan:
    """The steps to build `name` the way `analog` is built: non-test files first (so tests are written last), then
    the wiring (a file too long to rewrite that declares the analog gets the new declarations appended). Also the
    template of each new file, and what was left out and why: generated files (mocks are made by a tool, not
    rewritten), files too long to adapt in one go, and tests that use a mock that was left out."""
    own = set(files)
    left_out: list[str] = []
    usable: list[str] = []
    for f in sorted(files, key=lambda f: (bool(TEST_FILE.search(f)), f)):
        text = (work / f).read_text(encoding="utf-8", errors="replace")
        if GENERATED.search(text[:400]):
            left_out.append(f"`{f}`: generated by a tool")
        elif len(text) > SOURCE_BUDGET:
            left_out.append(f"`{f}`: too long to adapt in one go")
        elif TEST_FILE.search(f) and any("generated" in x for x in left_out) and re.search(r"\bmocks?\b", text):
            left_out.append(f"`{f}`: its mocks are generated by a tool")
        else:
            usable.append(f)
    ordered = usable[:MAX_ANALOG_FILES]
    a, n = pascal(analog), pascal(name)
    out = AnalogPlan(left_out=left_out)
    steps, templates = out.steps, out.templates
    for f in ordered:
        target = rename(f, analog, name)
        if target == f or (work / target).exists():
            continue
        templates[target] = f
        steps.append(
            PlannedStep(file=target, new=True, change=f"The same as {f}, for {n} instead of {a}: {request[:120]}")
        )
    found = wiring(work, analog, own)
    texts = {f: (work / f).read_text(encoding="utf-8", errors="replace") for f in found}
    declaring = {f for f in found if declared_blocks(texts[f], analog)}
    for f in sorted(found, key=lambda f: (f not in declaring, f))[:MAX_WIRING]:
        if len(texts[f]) > SOURCE_BUDGET:
            if f in declaring:
                out.appends[f] = declared_blocks(texts[f], analog)
            else:
                left_out.append(f"`{f}`: too long to change in one go; wire {n} in there by hand")
            continue
        steps.append(
            PlannedStep(
                file=f,
                change=f"Wire {n} in exactly where and how {a} is wired in this file (add next to it; remove nothing).",
            )
        )
    return out


def migration_steps(work: Path, analog: str, name: str) -> list[PlannedStep]:
    """A new numbered migration pair creating the new feature's table, shaped like the analog's, when the analog's
    table is created by the project's migrations."""
    from agent.playbooks.db_change import sql as dbsql  # noqa: PLC0415  (db_change imports the playbooks package)

    ups = sorted(p for d in ("migrations", "db/migrations", "database/migrations") for p in (work / d).glob("*.up.sql"))
    if not ups:
        return []
    table = None
    for f in ups:
        for m in dbsql.CREATE_TABLE.finditer(f.read_text(encoding="utf-8", errors="replace")):
            if snake(analog) in m.group(1).lower():
                table = re.sub(r"\s+", " ", m.group(0))[:700]
    if table is None:
        return []
    up, down = dbsql.next_migration(ups, work, f"add_{snake(name)}")
    return [
        PlannedStep(
            file=up,
            new=True,
            change=(
                f"PostgreSQL that creates the {snake(name)} table with a column for EVERY field of the new "
                f"{pascal(name)} model shown (same names and types), the way this creates the {analog} one: {table}"
            ),
        ),
        PlannedStep(file=down, new=True, change=f"PostgreSQL that drops what {up.rsplit('/', 1)[-1]} creates."),
    ]


# The order layers depend on each other in: data first, then what stores it, serves it and exposes it; tests last.
LAYERS = (
    ("model", "entity", "schema", "types"), ("domain", "dto"), ("repository", "repo", "store", "dao"),
    ("service", "usecase"), ("handler", "controller", "port", "route", "api", "view"),
)  # fmt: skip


def layer_rank(path: str) -> int:
    if TEST_FILE.search(path):
        return len(LAYERS) + 1
    if path.endswith(".sql"):
        return 1  # the table is written from the model, before anything stores into it
    low = path.lower()
    return next((i for i, words in enumerate(LAYERS) if any(w in low for w in words)), len(LAYERS))


def closest(answer: str, found: dict[str, list[str]]) -> str:
    """The existing feature a model's answer names, however it spelled it (`Wishlist`, `wishlists`, `the wishlist`)."""
    words = [snake(w) for w in re.findall(r"[A-Za-z][A-Za-z0-9_]*", answer)]
    for w in [snake(answer.strip()), *words]:
        for candidate in (w, w.rstrip("s"), w.removesuffix("es")):
            if candidate in found:
                return candidate
    return ""


def closest_in(paths: list[str], found: dict[str, list[str]]) -> str:
    """The existing feature the search ranked closest: the first reference file that belongs to one."""
    return next((s for p in paths if (s := stem_of(p)) in found), "")
