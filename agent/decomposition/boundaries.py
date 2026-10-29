"""Import-boundary rules: which module may import which, checked from the code's own imports.

This file uses only the standard library on purpose: Codewright copies it into a restructured project as
`architecture/check_boundaries.py`, so the rules keep being enforced (locally and in CI) after Codewright has left:

    python architecture/check_boundaries.py            # exit 1 on a new violation
    python architecture/check_boundaries.py --update   # accept the current state as the baseline

Rules live in `architecture/boundaries.json`:

    {"version": 1, "style": "modular_monolith" | "layers",
     "modules": {"order": ["shop/order"]},                # module → folders
     "public": {"order": ["shop/order/__init__.py"]},      # files other modules may import (modular monolith)
     "allow": {"order": ["user"]},                         # modules it may depend on (modular monolith)
     "layer_order": ["interface", "application", ...], "layers": {"order": "application"},   # layered
     "tables": {"orders": "order"},                        # table → the module that owns it
     "known": ["shop/a.py -> shop/b/c.py"]}                # accepted debt: only NEW violations fail

Imports are resolved for Python, TypeScript/JavaScript (relative paths), Go (import path suffix) and C++ (quoted
includes). Imports that cannot be resolved to a project file are ignored, never guessed.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target", "vendor"}
CODE = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".cpp", ".cc", ".cxx", ".hpp", ".h"}
JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs")
RULES_FILE = "architecture/boundaries.json"
JS_IMPORT = re.compile(r"""(?:from\s*|import\s*\(\s*|import\s+|require\(\s*)(['"])(\.{1,2}/[^'"]*|\.{1,2})\1""")
GO_IMPORT = re.compile(r'^\s*(?:import\s+)?(?:\w+\s+)?"([\w./-]+)"\s*$', re.M)
CPP_INCLUDE = re.compile(r'^\s*#\s*include\s*"([^"]+)"', re.M)
SQL_WRITE = re.compile(r"""\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+["`]?([A-Za-z_]\w*)""", re.I)
TABLE_DECL = re.compile(
    r"""(?:CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+["`]?([A-Za-z_]\w*)|__tablename__\s*=\s*["'](\w+)["'])""", re.I
)


@dataclass(frozen=True)
class Import:
    file: str
    line: int
    spec: str
    target: str | None  # the project file it resolves to (None: a package, an unknown path)
    source_module: str | None
    target_module: str | None


def code_files(work: Path) -> list[str]:
    return sorted(
        p.relative_to(work).as_posix()
        for p in work.rglob("*")
        if p.is_file() and p.suffix.lower() in CODE and not any(part in SKIP for part in p.relative_to(work).parts)
    )


def module_for(rules: dict[str, Any], rel: str | None) -> str | None:
    """The module a file belongs to (the longest matching folder)."""
    if rel is None:
        return None
    best: tuple[int, str] | None = None
    for name, folders in rules["modules"].items():
        for raw in folders:
            folder = raw.strip("/")
            if (folder in (".", rel) or rel.startswith(folder + "/")) and (best is None or len(folder) > best[0]):
                best = (len(folder), name)
    return best[1] if best else None


# ── resolving imports ────────────────────────────────────────────────────────
def py_roots(work: Path) -> list[str]:
    return [""] + (["src"] if (work / "src").is_dir() else [])


def py_dotted(rel: str, roots: list[str]) -> str | None:
    """`shop/order/service.py` → `shop.order.service` (the package root is the first of `roots` that contains it)."""
    for root in sorted(roots, key=len, reverse=True):
        if root and not rel.startswith(root + "/"):
            continue
        inner = rel[len(root) + 1 :] if root else rel
        if inner.endswith(".py"):
            inner = inner[:-3]
            inner = inner.removesuffix("/__init__") if inner.endswith("/__init__") else inner
            return inner.replace("/", ".") if inner != "__init__" else None
    return None


def py_file(dotted: str, files: set[str], roots: list[str]) -> str | None:
    base = dotted.replace(".", "/")
    for root in roots:
        prefix = f"{root}/" if root else ""
        for candidate in (f"{prefix}{base}.py", f"{prefix}{base}/__init__.py"):
            if candidate in files:
                return candidate
    return None


def py_imports(rel: str, source: str, files: set[str], roots: list[str]) -> list[tuple[int, str, str | None]]:
    """(line, spec, resolved file) for each import in a Python file."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    package = (py_dotted(rel, roots) or "").split(".")
    if not rel.endswith("__init__.py"):
        package = package[:-1]
    out: list[tuple[int, str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name, py_file(a.name, files, roots)) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                base = ".".join([*keep, *([node.module] if node.module else [])])
            else:
                base = node.module or ""
            for a in node.names:  # `from pkg import module` is the module's file, `from pkg import name` is pkg's
                found = py_file(f"{base}.{a.name}", files, roots) or py_file(base, files, roots)
                out.append((node.lineno, f"{base}.{a.name}" if a.name != "*" else base, found))
    return out


def js_resolve(rel: str, spec: str, files: set[str]) -> str | None:
    folder = Path(rel).parent
    parts: list[str] = [] if str(folder) == "." else list(folder.parts)
    for piece in spec.split("/"):
        if piece == "..":
            if not parts:
                return None
            parts.pop()
        elif piece not in (".", ""):
            parts.append(piece)
    base = "/".join(parts)
    for candidate in (base, *(base + e for e in JS_EXT), *(f"{base}/index{e}" for e in JS_EXT)):
        if candidate in files:
            return candidate
    return None


def scan_imports(work: Path, rules: dict[str, Any], only: list[str] | None = None) -> list[Import]:
    files = code_files(work)
    known = set(files)
    roots = py_roots(work)
    dirs = {str(Path(f).parent.as_posix()) for f in files}
    found: list[Import] = []
    for rel in only if only is not None else files:
        suffix = Path(rel).suffix.lower()
        try:
            text = (work / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits: list[tuple[int, str, str | None]] = []
        if suffix == ".py":
            hits = py_imports(rel, text, known, roots)
        elif suffix in JS_EXT:
            for m in JS_IMPORT.finditer(text):
                hits.append((text.count("\n", 0, m.start()) + 1, m.group(2), js_resolve(rel, m.group(2), known)))
        elif suffix == ".go":
            for m in GO_IMPORT.finditer(text):
                spec = m.group(1)
                folder = next((d for d in dirs if d and (spec == d or spec.endswith("/" + d))), None)
                if folder:
                    hits.append((text.count("\n", 0, m.start()) + 1, spec, f"{folder}/"))
        else:
            for m in CPP_INCLUDE.finditer(text):
                local = (Path(rel).parent / m.group(1)).as_posix().removeprefix("./")
                target = local if local in known else (m.group(1) if m.group(1) in known else None)
                hits.append((text.count("\n", 0, m.start()) + 1, m.group(1), target))
        for line, spec, target in hits:
            if target is not None and target != rel:
                found.append(
                    Import(rel, line, spec, target, module_for(rules, rel), module_for(rules, target.rstrip("/")))
                )
    return found


# ── tables ───────────────────────────────────────────────────────────────────
def scan_tables(work: Path, rules: dict[str, Any], files: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Table → the module that declares it (CREATE TABLE, __tablename__) and the modules that write it."""
    out: dict[str, dict[str, Any]] = {}
    for rel in (
        files
        if files is not None
        else code_files(work)
        + sorted(
            p.relative_to(work).as_posix()
            for p in work.rglob("*.sql")
            if not any(x in SKIP for x in p.relative_to(work).parts)
        )
    ):
        module = module_for(rules, rel)
        try:
            text = (work / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if module is None:
            continue
        for m in TABLE_DECL.finditer(text):
            out.setdefault((m.group(1) or m.group(2)).lower(), {"owner": None, "writers": set()})["owner"] = module
        for m in SQL_WRITE.finditer(text):
            name = m.group(1).lower()
            if name in {"set", "values", "select", "table"}:
                continue
            out.setdefault(name, {"owner": None, "writers": set()})["writers"].add(module)
    return {t: {"owner": v["owner"], "writers": sorted(v["writers"])} for t, v in sorted(out.items())}


# ── checking ─────────────────────────────────────────────────────────────────
def check(
    rules: dict[str, Any], imports: list[Import], tables: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Every violation: `{"key", "file", "line", "rule", "message", "known"}`; `known` ones are in the baseline."""
    style = rules.get("style", "modular_monolith")
    order = {name: i for i, name in enumerate(rules.get("layer_order", []))}
    out: list[dict[str, Any]] = []
    for imp in imports:
        a, b = imp.source_module, imp.target_module
        if a is None or b is None or a == b:
            continue
        key = f"{imp.file} -> {imp.target}"
        if style == "layers":
            la, lb = rules.get("layers", {}).get(a), rules.get("layers", {}).get(b)
            if la in order and lb in order and order[la] > order[lb]:
                out.append(
                    _v(key, imp, "layer", f"{a} ({la}) imports {b} ({lb}): dependencies must not point outward.")
                )
            continue
        if b not in rules.get("allow", {}).get(a, []):
            out.append(_v(key, imp, "not_allowed", f"{a} may not depend on {b}."))
        elif (
            imp.target
            and not imp.target.endswith("/")
            and rules.get("public", {}).get(b)
            and imp.target not in rules["public"][b]
        ):
            out.append(
                _v(key, imp, "internal", f"{a} imports {b}'s internals ({imp.target}); use its public interface.")
            )
    for table, info in (tables or {}).items():
        owner = rules.get("tables", {}).get(table) or info.get("owner")
        for writer in info.get("writers", []):
            if owner and writer != owner and style != "layers":
                key = f"table:{table}:{writer}"
                out.append({"key": key, "file": "", "line": 0, "rule": "table_owner", "known": key in rules.get("known", []),  # noqa: E501
                            "message": f"{writer} writes the table `{table}`, which {owner} owns."})  # fmt: skip
    return out


def _v(
    key: str,
    imp: Import,
    rule: str,
    message: str,
) -> dict[str, Any]:
    return {"key": key, "file": imp.file, "line": imp.line, "rule": rule, "message": message, "known": False}


def run(work: Path, rules: dict[str, Any]) -> list[dict[str, Any]]:
    found = check(rules, scan_imports(work, rules), scan_tables(work, rules))
    known = set(rules.get("known", []))
    for v in found:
        v["known"] = v["key"] in known
    return found


def main(argv: list[str]) -> int:
    work = Path(__file__).resolve().parent.parent
    rules_path = work / RULES_FILE
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    found = run(work, rules)
    if "--update" in argv:
        rules["known"] = sorted(v["key"] for v in found)
        rules_path.write_text(json.dumps(rules, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Baseline updated: {len(found)} known violation(s).")
        return 0
    new = [v for v in found if not v["known"]]
    for v in new:
        print(f"{v['file']}:{v['line']}: {v['message']}")
    print(f"{len(new)} new violation(s), {len(found) - len(new)} known.")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
