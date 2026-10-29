"""Incremental moves for the in-app targets (clean modules, modular monolith): small, mechanical changes that bring
the code closer to the approved design, each one tested and undone if it breaks anything.

No model rewrites a file here. The two kinds of move are exact text edits that the import scanner can check:

- **move**: a file that only another module uses is moved into that module, and every import of it is rewritten
  (Python and TypeScript/JavaScript).
- **expose**: other modules reach into a module's internals; the importer is pointed at the module's public entry
  (`__init__.py`) and the entry re-exports the name (Python).

Go and C++ get the design and the boundary rules, but their moves need the compiler (packages, headers), so they are
reported as not applied. This module also writes the rules file the checker enforces.
"""

from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.decomposition import boundaries as b
from agent.decomposition.layers import LAYERS

MAX_MOVES = 8
KEEP = {"main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "setup.py", "conftest.py", "__init__.py", "__main__.py"}
PY, JS = (".py",), b.JS_EXT


@dataclass
class Move:
    kind: str  # "move" | "expose"
    file: str
    to: str  # move: the folder; expose: the public entry file
    reason: str
    importers: list[str] = field(default_factory=list)

    def title(self) -> str:
        return (
            f"Move `{self.file}` into `{self.to}`"
            if self.kind == "move"
            else f"Expose `{self.file}` through `{self.to}`"
        )


@dataclass
class Edit:
    """What a move changes: files to write (path → text) and files to delete."""

    writes: dict[str, str] = field(default_factory=dict)
    deletes: list[str] = field(default_factory=list)


# ── rules from a design ──────────────────────────────────────────────────────
def module_folders(name: str) -> str:
    return "." if name == "(root)" else name


def rules_from_modules(work: Path, design: dict[str, Any]) -> dict[str, Any]:
    """Boundary rules for a modular monolith: the groups are the modules, the calls in the design are the allowed
    dependencies, and each group exposes `__init__.py` / `index.*` / `api.*` when it has one."""
    files = b.code_files(work)
    modules = {g["name"]: [module_folders(m) for m in g["modules"]] for g in design["groups"]}
    rules: dict[str, Any] = {"version": 1, "style": "modular_monolith", "modules": modules, "public": {}, "allow": {}}
    for g in design["groups"]:
        allowed = set(g["calls"]) - {g["name"]}
        if g["kind"] == "frontend":
            allowed = {x["name"] for x in design["groups"]} - {g["name"]}  # the UI may use any module's interface
        rules["allow"][g["name"]] = sorted(allowed)
        public = [
            f
            for f in files
            if b.module_for(rules, f) == g["name"] and _is_entry(f) and Path(f).suffix.lower() in (*PY, *JS)
        ]
        if public:
            rules["public"][g["name"]] = public
    tables = b.scan_tables(work, rules)
    rules["tables"] = {
        t: v["owner"] or v["writers"][0] for t, v in tables.items() if v["owner"] or len(v["writers"]) == 1
    }
    return rules


def _is_entry(rel: str) -> bool:
    name = Path(rel).name.lower()
    return name == "__init__.py" or name.rsplit(".", 1)[0] in ("index", "api", "public")


def rules_from_layers(design: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "style": "layers",
        "modules": {m: [module_folders(m)] for m in design["assignment"]},
        "layer_order": list(LAYERS),
        "layers": design["assignment"],
    }


# ── planning ─────────────────────────────────────────────────────────────────
def plan_moves(
    work: Path, rules: dict[str, Any], imports: list[b.Import] | None = None
) -> tuple[list[Move], list[str]]:
    """(moves, notes): up to MAX_MOVES mechanical moves, and what could not be done by machine and why."""
    imports = imports if imports is not None else b.scan_imports(work, rules)
    notes: list[str] = []
    moves: list[Move] = []
    by_target: dict[str, list[b.Import]] = {}
    for imp in imports:
        if imp.target:
            by_target.setdefault(imp.target, []).append(imp)
    for target, ims in sorted(by_target.items()):
        owner = b.module_for(rules, target)
        suffix = Path(target).suffix.lower()
        if owner is None or Path(target).name in KEEP or "test" in Path(target).parts or target.endswith("/"):
            continue
        outside = [i for i in ims if i.source_module not in (None, owner)]
        inside = [i for i in ims if i.source_module == owner]
        if not outside:
            continue
        if suffix not in (*PY, *JS):
            notes.append(
                f"`{target}` is used across modules, but {suffix or 'this'} files can't be moved mechanically."
            )
            continue
        users = {i.source_module for i in outside}
        if not inside and len(users) == 1:
            user = next(iter(users))
            folder = _folder_for(rules, user, outside) if user else None
            if folder and (work / target).read_text(encoding="utf-8", errors="replace").count("__main__") == 0:
                moves.append(Move("move", target, folder, f"only `{user}` uses it", sorted({i.file for i in outside})))
                continue
        entry = (rules.get("public", {}).get(owner) or [None])[0]
        if suffix == ".py" and entry and target not in rules["public"][owner]:
            if any(
                i.source_module is not None and owner not in rules.get("allow", {}).get(i.source_module, [])
                for i in outside
            ):
                continue  # a forbidden dependency can't be fixed by exposing it
            moves.append(
                Move(
                    "expose",
                    target,
                    entry,
                    f"{len(outside)} import(s) from other modules reach into it",
                    sorted({i.file for i in outside}),
                )
            )
    moves.sort(key=lambda m: (m.kind != "move", -len(m.importers), m.file))
    if len(moves) > MAX_MOVES:
        notes.append(f"{len(moves) - MAX_MOVES} more move(s) were found; the first {MAX_MOVES} are done in this run.")
    return moves[:MAX_MOVES], notes


def _folder_for(rules: dict[str, Any], module: str, imports: list[b.Import]) -> str | None:
    folders = [f for f in rules["modules"].get(module, []) if f != "."]
    if not folders:
        return None
    dirs = [str(Path(i.file).parent.as_posix()) for i in imports]
    inside = [f for f in folders if any(d == f or d.startswith(f + "/") for d in dirs)]
    folder: str = (inside or folders)[0]
    return folder


# ── making a move ────────────────────────────────────────────────────────────
class CannotMove(Exception):
    pass


def make_edit(work: Path, move: Move) -> Edit:
    """The exact change for a move, or CannotMove with the reason (nothing is written)."""
    if move.kind == "expose":
        return _expose_py(work, move)
    dst = f"{move.to}/{Path(move.file).name}"
    if (work / dst).exists():
        raise CannotMove(f"`{dst}` already exists")
    suffix = Path(move.file).suffix.lower()
    return _move_py(work, move.file, dst) if suffix == ".py" else _move_js(work, move.file, dst)


def apply_edit(work: Path, edit: Edit) -> dict[str, str | None]:
    """Write the edit; returns the originals (None = did not exist) to undo it with `restore`."""
    before: dict[str, str | None] = {}
    for rel in [*edit.writes, *edit.deletes]:
        path = work / rel
        before[rel] = path.read_text(encoding="utf-8") if path.is_file() else None
    for rel in edit.deletes:
        (work / rel).unlink(missing_ok=True)
    for rel, text in edit.writes.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8")
    return before


def restore(work: Path, before: dict[str, str | None]) -> None:
    for rel, text in before.items():
        if text is None:
            (work / rel).unlink(missing_ok=True)
        else:
            (work / rel).write_text(text, encoding="utf-8")


def _read(work: Path, rel: str) -> str:
    return (work / rel).read_text(encoding="utf-8", errors="replace")


def _move_py(work: Path, src: str, dst: str) -> Edit:
    files = set(b.code_files(work))
    roots = b.py_roots(work)
    old, new = b.py_dotted(src, roots), b.py_dotted(dst, roots)
    if not old or not new:
        raise CannotMove("it isn't inside an importable package")
    edit = Edit(deletes=[src])
    for rel in sorted(f for f in files if f.endswith(".py")):
        text = _read(work, rel)
        rewritten = _rewrite_py(rel, text, {old: new}, files, roots, absolute=(rel == src))
        if rel == src:
            edit.writes[dst] = rewritten
        elif rewritten != text:
            edit.writes[rel] = rewritten
    return edit


def _rewrite_py(  # noqa: PLR0912  (imports come in four shapes)
    rel: str, text: str, rename: dict[str, str], files: set[str], roots: list[str], *, absolute: bool
) -> str:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise CannotMove(f"`{rel}` doesn't parse ({exc.msg})") from exc
    package = (b.py_dotted(rel, roots) or "").split(".")
    if not rel.endswith("__init__.py"):
        package = package[:-1]
    lines = text.split("\n")
    changes: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in rename or any(a.name.startswith(k + ".") for k in rename):
                    if a.asname is None:
                        raise CannotMove(f"`{rel}` uses `import {a.name}` without an alias")
                    new = rename.get(a.name) or a.name
                    changes.append(
                        (
                            node.lineno,
                            node.end_lineno or node.lineno,
                            f"{' ' * node.col_offset}import {new} as {a.asname}",
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            keep = package[: len(package) - (node.level - 1)] if node.level > 1 else package
            base = ".".join([*keep, *([node.module] if node.module else [])]) if node.level else (node.module or "")
            parts: dict[str, list[str]] = {}
            touched = False
            for a in node.names:
                full = f"{base}.{a.name}"
                if full in rename:  # a moved module imported by name
                    target_base, name = rename[full].rsplit(".", 1) if "." in rename[full] else ("", rename[full])
                    parts.setdefault(target_base, []).append(_alias(name, a.asname))
                    touched = True
                else:
                    module = rename.get(base, base)
                    touched |= module != base
                    parts.setdefault(module, []).append(_alias(a.name, a.asname))
            if node.level and absolute and base:
                touched = True
            if touched:
                text_ = "\n".join(f"{' ' * node.col_offset}from {m} import {', '.join(n)}" for m, n in parts.items())
                changes.append((node.lineno, node.end_lineno or node.lineno, text_))
    for start, end, new in sorted(changes, reverse=True):
        lines[start - 1 : end] = new.split("\n")
    return "\n".join(lines)


def _alias(name: str, asname: str | None) -> str:
    return f"{name} as {asname}" if asname else name


def _expose_py(work: Path, move: Move) -> Edit:
    roots = b.py_roots(work)
    target_mod, entry_mod = b.py_dotted(move.file, roots), b.py_dotted(move.to, roots)
    if not target_mod or not entry_mod:
        raise CannotMove("it isn't inside an importable package")
    edit = Edit()
    exported: list[str] = []
    for rel in move.importers:
        if not rel.endswith(".py"):
            continue
        text = edit.writes.get(rel) or _read(work, rel)
        package = (b.py_dotted(rel, roots) or "").split(".")
        if not rel.endswith("__init__.py"):
            package = package[:-1]
        tree = ast.parse(text)
        lines = text.split("\n")
        changes: list[tuple[int, int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            keep = package[: len(package) - (node.level - 1)] if node.level > 1 else package
            base = ".".join([*keep, *([node.module] if node.module else [])]) if node.level else (node.module or "")
            if base != target_mod or any(a.name == "*" for a in node.names):
                continue
            names = [_alias(a.name, a.asname) for a in node.names]
            exported += [a.name for a in node.names]
            changes.append(
                (
                    node.lineno,
                    node.end_lineno or node.lineno,
                    f"{' ' * node.col_offset}from {entry_mod} import {', '.join(names)}",
                )
            )
        if not changes:
            continue
        for start, end, new in sorted(changes, reverse=True):
            lines[start - 1 : end] = [new]
        edit.writes[rel] = "\n".join(lines)
    if not exported:
        raise CannotMove("no `from … import …` of it was found to point at the entry")
    entry = edit.writes.get(move.to) or _read(work, move.to)
    relative = target_mod.removeprefix(entry_mod + ".") if target_mod.startswith(entry_mod + ".") else target_mod
    prefix = "." if target_mod.startswith(entry_mod + ".") else ""
    have = set(re.findall(r"^\s*from\s+\S+\s+import\s+(.+)$", entry, re.M))
    missing = sorted({n for n in exported if not any(re.search(rf"\b{re.escape(n)}\b", h) for h in have)})
    if missing:
        entry = (
            entry.rstrip("\n")
            + f"\nfrom {prefix}{relative} import {', '.join(missing)}  # noqa: F401  (public interface)\n"
        )
    edit.writes[move.to] = entry
    return edit


def _move_js(work: Path, src: str, dst: str) -> Edit:
    files = set(b.code_files(work))
    mapping = {src: dst}
    edit = Edit(deletes=[src])
    for rel in sorted(f for f in files if f.endswith(b.JS_EXT)):
        text = _read(work, rel)
        origin_dir = Path(rel).parent
        new_dir = Path(mapping.get(rel, rel)).parent

        def swap(m: re.Match[str], rel: str = rel, origin_dir: Path = origin_dir, new_dir: Path = new_dir) -> str:
            spec = m.group(2)
            target = b.js_resolve(rel, spec, files)
            if src not in (rel, target):
                return m.group(0)
            raw = Path(os.path.normpath(origin_dir / spec)).as_posix()
            real = mapping.get(target or raw, target or raw)
            new = _relative_spec(new_dir, real, spec, target)
            return m.group(0).replace(spec, new, 1)

        rewritten = b.JS_IMPORT.sub(swap, text)
        if rel == src:
            edit.writes[dst] = rewritten
        elif rewritten != text:
            edit.writes[rel] = rewritten
    return edit


def _relative_spec(from_dir: Path, target: str, old_spec: str, resolved: str | None) -> str:
    path = target
    had_ext = old_spec.endswith(b.JS_EXT) or resolved is None
    if not had_ext and resolved:
        path = re.sub(r"\.(ts|tsx|js|jsx|mjs)$", "", path)
        if Path(path).name == "index" and not old_spec.rstrip("/").endswith("index"):
            path = str(Path(path).parent)
    spec = Path(os.path.relpath(path, from_dir or ".")).as_posix()
    return spec if spec.startswith(".") else f"./{spec}"


def write_rules(work: Path, rules: dict[str, Any], explanation: str) -> list[str]:
    """`architecture/boundaries.json`, the checker next to it and a README saying what the rules mean."""
    folder = work / "architecture"
    folder.mkdir(exist_ok=True)
    (folder / "boundaries.json").write_text(json.dumps(rules, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (folder / "check_boundaries.py").write_text(Path(b.__file__).read_text(encoding="utf-8"), encoding="utf-8")
    (folder / "README.md").write_text(explanation.rstrip() + "\n", encoding="utf-8")
    return ["architecture/boundaries.json", "architecture/check_boundaries.py", "architecture/README.md"]
