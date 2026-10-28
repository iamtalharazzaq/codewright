"""Explain (`explain_code`, CODEWRIGHT.md Section 5.3): graph + search answers with a diagram.

1. Code Analyst: the symbols and modules the question names → Graphify `explain` (exact node; an ambiguous name is
   resolved to its implementation, not a mock, test or generated file) + code search hits + the module map.
2. The answer streams in the chat (see `agent/chat/answer.py`, with `EXPLAIN_RULES` added).
3. One structured call turns the answer into flow steps; the Mermaid diagram is drawn from them here, so a 9B model
   never has to write Mermaid syntax. It goes to the Diagram tab; the modules used are highlighted in the Graph tab.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent.llm.client import LLMClient
from agent.llm.structured import structured

GRAPHIFY_CHARS = 700  # per explained symbol
MAX_SYMBOLS = 2
BODY_LINES = 130  # of each definition's source, at most
DOC_LINES = 8  # comment lines just above a definition, kept with it
SOURCE_CHARS = 5200  # everything Explain adds: the GPU model has a 4K context and the answer needs ~1,200 tokens
USAGES = 6
MAX_SOURCE_BYTES = 300_000
MAX_STEPS = 10

EXPLAIN_RULES = """This is an explanation of the user's code. Lead with a two-sentence summary, then walk through the
flow step by step. Give each step the file path and line from the context, like `src/billing/invoice.py` L42, with
the full path at least once per file. Cover the whole function, to its end. Describe what the source in the context
does; don't write "likely", "probably" or "typically" about code you were shown, and don't add steps it doesn't show.
If something isn't in the context, say which file you'd need to see. No diagram and no Mermaid: Codewright draws it
from your answer."""

NOTHING_FOUND = """No code in this project matched the question (no definition, graph node or search hit). Say so
plainly, say which file or name would help, and don't describe code you haven't been shown."""

# CamelCase / camelCase / snake_case / dotted names / call syntax: PlaceOrder, placeOrder, place_order, Order.Pay, pay()
_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)(\(\))?")
_COMMON = {
    "How", "What", "Why", "Where", "When", "Which", "Who", "Does", "Explain", "Show", "Tell", "The", "This", "That",
    "Can", "Could", "Please", "And", "From", "With", "API", "HTTP", "JSON", "SQL", "REST", "Go", "Python", "I",
}  # fmt: skip
_AMBIGUOUS_PATH = re.compile(r"^\s{2}(\S+\.\w+)\s*$", re.M)
_WEAK_PATH = re.compile(r"(mock|_test\.|\.test\.|/tests?/|\.pb\.go$|_pb2\.py$|generated|/gen/|\.d\.ts$)", re.I)
# Entry points (handlers, routes, transports) explain less than the implementation they call, so they come after it.
_ENTRY_PATH = re.compile(
    r"(^|/)(ports?|handlers?|controllers?|routes?|routers?|api|http|grpc|transport|cmd|views?)(/|\.)", re.I
)
_DOC_LINE = re.compile(r"^\s*(//|#(?!include|define|if|endif|pragma)|/\*|\*|\"\"\"|''')")
# Any top-level definition line, for a module's outline (all 5 languages).
_OUTLINE = re.compile(
    r"^(?:func[ \t]|type[ \t]+\w+[ \t]+(?:struct|interface)|(?:async[ \t]+)?def[ \t]|class[ \t]"
    r"|(?:export[ \t]+)?(?:default[ \t]+)?(?:async[ \t]+)?(?:function|class|interface)[ \t])"
)


def find_symbols(question: str) -> list[str]:
    """Names in the question that look like code: `PlaceOrder`, `place_order`, `order.Pay`, `pay()`, `MAX_RETRIES`."""
    found: list[str] = []
    for name, call in _IDENT.findall(question):
        code_like = (
            bool(call)
            or "_" in name
            or "." in name
            or bool(re.search(r"[a-z][A-Z]|^[A-Z][a-z]+[A-Z]|^[A-Z]{2,}[a-z]", name))
        )
        if code_like and name not in _COMMON and name not in found:
            found.append(name)
    return found[:MAX_SYMBOLS]


_WORD = re.compile(r"`([A-Za-z_][\w.]*)`|(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,}[A-Za-z]*)\b")


def defined_names(question: str, files: list[tuple[str, list[str]]]) -> list[str]:
    """Plain words that may be code (`Login`, `checkout` in backticks) and that the project defines."""
    words = [a or b for a, b in _WORD.findall(question.strip())]
    words = [w for w in dict.fromkeys(words) if w not in _COMMON][:4]
    return [w for w in words if any(_definition(w).match(line) for _, lines in files for line in lines)][:MAX_SYMBOLS]


def modules_in(question: str, module_ids: Sequence[str]) -> list[str]:
    """Modules the question names by their last folder: "payment" → internal/payment."""
    words = set(re.findall(r"[a-z][a-z0-9_-]+", question.lower()))
    words |= {w.rstrip("s") for w in words}
    return [m for m in module_ids if m.rsplit("/", 1)[-1].lower() in words]


def resolve(name: str, ask: Callable[[str], str]) -> str:
    """Graphify `explain` for `name`, choosing the implementation when the name is ambiguous."""
    first = ask(name)
    if not first.startswith("Ambiguous"):
        return first
    paths = _AMBIGUOUS_PATH.findall(first)
    strong = [p for p in paths if not _WEAK_PATH.search(p)] or paths
    if not strong:
        return first
    # Prefer a file whose path mentions the symbol's own words (order.go for PlaceOrder), then service/domain code.
    words = [w.lower() for w in re.findall(r"[A-Z]?[a-z]+", name)]
    strong.sort(key=lambda p: (-sum(w in p.lower() for w in words), "service" not in p, len(p)))
    member = name.rsplit(".", 1)[-1]
    for candidate in (f"{strong[0]}::.{member}()", f"{strong[0]}::{member}", f"{strong[0]}::{member}()"):
        answer = ask(candidate)
        if answer.startswith("Node:"):
            return answer
    return first


_CODE_SUFFIXES = {".go", ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cc", ".cpp", ".cxx", ".h", ".hpp"}
_SKIP_PARTS = {".git", "node_modules", "vendor", "dist", "build", ".venv", "graphify-out", ".codewright"}


def _definition(name: str) -> re.Pattern[str]:
    """Where `name` is defined, in any of the 5 languages: a function or method with a body, a type or class, a
    constant or a module-level variable (not a call, a declaration in an interface or a use)."""
    n = re.escape(name.rsplit(".", 1)[-1])
    snake = re.escape(re.sub(r"(?<!^)(?=[A-Z])", "_", name.rsplit(".", 1)[-1]).lower())
    # One line each ([ \t], never \s: a match must not run on into the next lines).
    return re.compile(
        rf"^[ \t]*(?:func[ \t]+(?:\([^)\n]*\)[ \t]*)?{n}[ \t]*\(.*\{{[ \t]*$"  # Go func, with a body
        rf"|^[ \t]*(?:type|const|var)[ \t]+{n}\b"  # Go type / const / var
        rf"|^\t{n}[ \t]*(?:[\w.*\[\]]+[ \t]*)?=[^=]"  # Go, inside a const ( ... ) block
        rf"|^[ \t]*(?:async[ \t]+)?def[ \t]+(?:{n}|{snake})[ \t]*\("  # Python function
        rf"|^[ \t]*class[ \t]+{n}\b"  # Python / JS / TS / C++ class
        rf"|^(?:{n}|{snake})[ \t]*(?::[^=\n]+)?=[^=]"  # Python module-level constant
        rf"|^[ \t]*(?:export[ \t]+)?(?:default[ \t]+)?(?:async[ \t]+)?function[ \t]+{n}[ \t]*\("  # JS/TS function
        rf"|^[ \t]*(?:export[ \t]+)?(?:declare[ \t]+)?(?:abstract[ \t]+)?(?:interface|enum|type)[ \t]+{n}\b"  # TS
        rf"|^[ \t]*(?:export[ \t]+)?(?:const|let|var)[ \t]+{n}\b"  # JS/TS constant, arrow function
        rf"|^[ \t]*(?:(?:public|private|protected|static|async)[ \t]+)*{n}[ \t]*\([^;\n]*\)[ \t]*"
        rf"(?::[ \t]*[^={{;\n]+)?\{{[ \t]*$"  # methods
        rf"|^[\w:<>,* \t&]*\b{n}[ \t]*\([^;\n]*\)[ \t]*(?:const[ \t]*)?\{{[ \t]*$"  # C++ function definitions
        rf"|^[ \t]*(?:struct|enum(?:[ \t]+class)?)[ \t]+{n}\b[^;\n]*$"  # C++ struct / enum (not a forward declaration)
        rf"|^[ \t]*#define[ \t]+{n}\b|^[ \t]*(?:static[ \t]+)?constexpr\b[^;\n]*\b{n}[ \t]*[={{])",  # C++ constants
        re.M,
    )


def _body_end(lines: list[str], start: int) -> int:
    """The line after the definition starting at `start`: brackets balanced (Go, JS/TS, C++, a multi-line value) or
    the indented block ends (Python)."""
    first = lines[start]
    limit = min(len(lines), start + BODY_LINES)
    if first.rstrip().endswith(":") and re.match(r"\s*(async\s+)?(def|class)\s", first):
        indent = len(first) - len(first.lstrip())
        end = start + 1
        while end < limit and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > indent):
            end += 1
        return end
    depth = 0
    for i in range(start, limit):
        depth += sum(lines[i].count(c) for c in "{([") - sum(lines[i].count(c) for c in "})]")
        if depth <= 0:
            return i + 1
    return limit


def _doc_start(lines: list[str], start: int) -> int:
    """The first line of the comment just above a definition (its documentation), or `start`."""
    top = start
    while top > 0 and start - top < DOC_LINES and _DOC_LINE.match(lines[top - 1]):
        top -= 1
    return top


def _numbered(lines: list[str], start: int, end: int) -> str:
    """Numbered source lines (blank lines dropped: they cost tokens and the numbers keep the place)."""
    return "\n".join(f"{n + 1:>5}  {lines[n]}" for n in range(start, end) if lines[n].strip())


def _rank(rel: str, name: str) -> tuple[int, int, int]:
    """Implementation before entry points; then files named after the symbol's words (order.go for PlaceOrder)."""
    words = [w.lower() for w in re.findall(r"[A-Z]?[a-z]+", name.rsplit(".", 1)[-1])]
    return (bool(_ENTRY_PATH.search(rel)), -sum(w in rel.lower() for w in words), len(rel))


def _code_files(work: Path) -> list[tuple[str, list[str]]]:
    """(path, lines) of every code file worth reading: no mocks, tests, generated or vendored code."""
    out: list[tuple[str, list[str]]] = []
    for path in sorted(work.rglob("*")):
        rel = path.relative_to(work)
        if (
            path.suffix not in _CODE_SUFFIXES
            or any(p in _SKIP_PARTS for p in rel.parts)
            or _WEAK_PATH.search(rel.as_posix())
            or not path.is_file()
            or path.stat().st_size > MAX_SOURCE_BYTES
        ):
            continue
        out.append((rel.as_posix(), path.read_text(encoding="utf-8", errors="replace").splitlines()))
    return out


def _cut(text: str, room: int) -> str:
    return text if len(text) <= room else text[: max(0, text.rfind("\n", 0, room))] + "\n  ... (cut)"


def definitions(
    work: Path,
    name: str,
    limit: int = 3,
    budget: int = SOURCE_CHARS,
    files: list[tuple[str, list[str]]] | None = None,
    shown: set[tuple[str, int]] | None = None,
) -> list[str]:
    """The source of `name`'s definitions (numbered, with their doc comment, each cut at its end), skipping mocks,
    tests and generated files: the implementation first, then its entry points, within `budget` characters. The
    (file, line) pairs shown are added to `shown`."""
    pattern = _definition(name)
    candidates: list[tuple[str, list[str], int]] = []
    for rel, lines in files if files is not None else _code_files(work):
        candidates += [(rel, lines, i) for i, line in enumerate(lines) if pattern.match(line)]
    found: list[str] = []
    for rel, lines, start in sorted(candidates, key=lambda c: (_rank(c[0], name), c[2]))[:limit]:
        head = f"Source of {name} in {rel}:\n```\n"
        room = budget - len(head) - 4
        if room < 300:
            break
        top, end = _doc_start(lines, start), _body_end(lines, start)
        body = _cut(_numbered(lines, top, end), room)
        found.append(f"{head}{body}\n```")
        if shown is not None:
            shown |= {(rel, n + 1) for n in range(top, end)}
        budget -= len(found[-1])
    return found


def usages(name: str, files: list[tuple[str, list[str]]], skip: set[tuple[str, int]], limit: int = USAGES) -> str:
    """Where `name` is used (file:line and the line), outside its own definitions."""
    word = re.compile(rf"\b{re.escape(name.rsplit('.', 1)[-1])}\b")
    hits: list[str] = []
    for rel, lines in sorted(files, key=lambda f: bool(_ENTRY_PATH.search(f[0]))):
        for i, line in enumerate(lines):
            if (rel, i + 1) not in skip and word.search(line) and not _DOC_LINE.match(line):
                hits.append(f"- {rel} L{i + 1}: {line.strip()[:140]}")
                if len(hits) >= limit:
                    return f"{name} is used at:\n" + "\n".join(hits)
    return f"{name} is used at:\n" + "\n".join(hits) if hits else ""


def module_brief(
    module: str, graph: dict[str, Any], files: list[tuple[str, list[str]]], budget: int
) -> str:  # fmt: skip
    """A module the question names: what it defines (its outline) and the code behind each of its dependencies."""
    mine = [(rel, lines) for rel, lines in files if rel == module or rel.startswith(module.rstrip("/") + "/")]
    outline = [
        f"- {rel} L{i + 1}: {line.strip()[:110]}"
        for rel, lines in sorted(mine, key=lambda f: bool(_ENTRY_PATH.search(f[0])))
        for i, line in enumerate(lines)
        if _OUTLINE.match(line)
    ]
    parts = [f"Module {module} defines:\n" + "\n".join(outline[:24])] if outline else []
    for direction, edges in (
        ("depends on", [e for e in graph.get("edges", []) if e["source"] == module and e.get("weight", 0) > 0]),
        ("is used by", [e for e in graph.get("edges", []) if e["target"] == module and e.get("weight", 0) > 0]),
    ):
        for e in sorted(edges, key=lambda e: -e.get("weight", 0))[:6]:
            other = e["target"] if direction == "depends on" else e["source"]
            look_in, look_for = (mine, other) if direction == "depends on" else (
                [(r, ls) for r, ls in files if r.startswith(other.rstrip("/") + "/")], module
            )  # fmt: skip
            needle = re.compile(re.escape(look_for) + "|" + re.escape(look_for.replace("/", ".")))
            evidence = [
                f"{rel} L{i + 1}: {line.strip()[:100]}"
                for rel, lines in sorted(look_in, key=lambda f: bool(_ENTRY_PATH.search(f[0])))
                for i, line in enumerate(lines)
                if needle.search(line)
            ][:3]
            relations = ", ".join(f"{k} {v}" for k, v in (e.get("relations") or {}).items())
            note = f" ({e['note']})" if e.get("note") else ""
            parts.append(
                f"{module} {direction} {other}: {relations or e.get('weight')}{note}"
                + "".join(f"\n    {x}" for x in evidence)
            )
    return _cut("\n".join(parts), budget)


@dataclass
class ExplainContext:
    text: str
    modules: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    has_code: bool = False  # definitions or a module brief were found: the generic search snippets aren't needed


def gather(
    question: str,
    module_ids: Sequence[str],
    explain: Callable[[str], str] | None,
    hits: Sequence[dict[str, Any]],
    work: Path | None = None,
    graph: dict[str, Any] | None = None,
) -> ExplainContext:
    """The Code Analyst's findings for the prompt (all of it data, not instructions): the source of each symbol the
    question names and where it's used, the modules it names with their dependencies, and graph facts, so the answer
    describes the code rather than guessing. Everything fits in `SOURCE_CHARS`."""
    parts: list[str] = []
    files: list[str] = []
    budget = SOURCE_CHARS
    symbols = find_symbols(question)
    named = modules_in(question, module_ids)
    code = _code_files(work) if work is not None else []
    symbols = symbols or defined_names(question, code)
    for name in symbols:
        shown: set[tuple[str, int]] = set()
        share = int(budget * 0.8) // len(symbols)
        sources = definitions(work, name, budget=share, files=code, shown=shown) if work else []
        files += [s.split(" in ", 1)[1].split(":", 1)[0] for s in sources]
        parts += sources
        used = usages(name, code, shown)
        if used:
            parts.append(_cut(used, 900))
    budget -= sum(len(p) for p in parts)
    if graph is not None and not symbols:
        for module in named[:2]:
            if budget > 400 and (brief := module_brief(module, graph, code, budget // max(1, len(named[:2])))):
                parts.append(brief)
                budget -= len(brief)
    has_code = bool(parts)
    if explain is not None:
        for name in symbols:
            try:
                answer = resolve(name, explain)
            except Exception as exc:  # Graphify missing or failing must not stop the answer
                answer = f"(graph lookup failed: {exc})"
            if answer.startswith("Node:"):
                if budget > 300:
                    parts.append(f"Graph facts for {name}:\n{answer[: min(GRAPHIFY_CHARS, budget)]}")
                    budget -= len(parts[-1])
                if m := re.search(r"Source:\s+(\S+)", answer):
                    files.append(m.group(1))
    files += [h["path"] for h in hits if not _WEAK_PATH.search(h["path"])]
    from_files = [m for m in module_ids if any(f == m or f.startswith(m + "/") for f in files)]
    modules = list(dict.fromkeys(named + from_files))
    if not parts and not hits:
        parts.append(NOTHING_FOUND)
    return ExplainContext("\n\n".join(parts), modules, list(dict.fromkeys(files)), has_code)


# ── the diagram ──────────────────────────────────────────────────────────────
class FlowStep(BaseModel):
    source: str = Field(
        description="Who acts: a module, component or actor (e.g. 'Client', 'API handler', 'database')."
    )
    target: str = Field(description="Who it calls or sends to.")
    action: str = Field(description="What happens, 2-8 words (e.g. 'POST /orders', 'charge card').")


class FlowDiagram(BaseModel):
    kind: Literal["sequence", "flowchart"] = Field(
        description="sequence: calls between parts over time; flowchart: decisions and steps."
    )
    title: str = Field(description="At most 8 words.")
    steps: list[FlowStep] = Field(min_length=1, max_length=MAX_STEPS)


DIAGRAM_SYSTEM = """You turn an explanation of code into the steps of one diagram. Reply with JSON only.
Use the parts named in the explanation (modules, services, handlers, the database), at most 6 parts, in the order
things happen. Never add steps the explanation doesn't describe."""


async def diagram(client: LLMClient, question: str, answer: str) -> dict[str, Any] | None:
    """The explanation as a diagram: {"title", "kind", "mermaid"}, or None when there is no flow to draw."""
    if len(answer) < 80:
        return None
    result = await structured(
        client,
        FlowDiagram,
        [
            {"role": "system", "content": DIAGRAM_SYSTEM},
            {"role": "user", "content": f"Question: {question[:300]}\n\nExplanation:\n{answer[:3500]}"},
        ],
        task="explain_diagram",
        max_tokens=600,
    )
    flow = result.value
    if not any(_named(step) for step in flow.steps):
        return None
    return {"title": flow.title, "kind": flow.kind, "mermaid": to_mermaid(flow)}


def _label(text: str, limit: int = 60) -> str:
    """Text Mermaid can't misread: no quotes, brackets, semicolons, arrows or HTML."""
    text = re.sub(r"[-=]+>", " to ", text)  # arrows first: their ">" would go below
    text = re.sub(r"[\"'`;#<>{}\[\]|]", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:limit] or "?"


def _named(step: FlowStep) -> bool:
    """Both ends of the step are named parts (a 9B model sometimes leaves one empty)."""
    return _label(step.source, 40) != "?" and _label(step.target, 40) != "?"


def _ids(names: list[str]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for name in names:
        base = re.sub(r"[^A-Za-z0-9]", "_", name).strip("_") or "part"
        base = base if base[0].isalpha() else f"p_{base}"
        ident, n = base, 2
        while ident in ids.values():
            ident, n = f"{base}_{n}", n + 1
        ids[name] = ident
    return ids


def to_mermaid(flow: FlowDiagram) -> str:
    flow = flow.model_copy(update={"steps": [s for s in flow.steps if _named(s)] or flow.steps})
    names = list(dict.fromkeys(_label(n, 40) for s in flow.steps for n in (s.source, s.target)))
    ids = _ids(names)
    if flow.kind == "sequence":
        lines = ["sequenceDiagram", "    autonumber"]
        lines += [f"    participant {ids[n]} as {n}" for n in names]
        lines += [
            f"    {ids[_label(s.source, 40)]}->>{ids[_label(s.target, 40)]}: {_label(s.action)}" for s in flow.steps
        ]
    else:
        lines = ["flowchart TD"]
        lines += [f'    {ids[n]}["{n}"]' for n in names]
        lines += [
            f'    {ids[_label(s.source, 40)]} -->|"{_label(s.action, 40)}"| {ids[_label(s.target, 40)]}'
            for s in flow.steps
        ]
    return "\n".join(lines)
