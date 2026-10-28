"""Shared by Bug fix (5.7) and Tests (5.6): placing Codewright's own test file for a source file, writing a model's
full-file answer safely, finding which component a file belongs to, and reading a `project.test()` report for the
Reflection loop's feedback. Every write is the complete new content of one file (like `write_docs`'s corrections):
a 9B model rewriting a whole small file is far more reliable than it patching one, and the diff the user reviews is
computed from the result, not trusted from the model.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.language_packs import detect_project
from agent.language_packs.base import Component

MAX_FAILURE_CHARS = 1200

# Per pack, the file Codewright writes its own tests into: next to the conventional one, never replacing it. A
# model that sees the first 3000 characters of a long test file can't be trusted to hand the rest back unchanged.
_EXTRA: dict[str, str] = {
    "python": "{dir}test_{stem}_codewright.py",
    "go": "{dir}{stem}_codewright_test.go",
    "typescript": "{dir}{stem}.codewright.test.ts",
    "javascript": "{dir}{stem}.codewright.test.js",
    "cpp": "{dir}{stem}_codewright_test.cpp",
}


def own_test_file(pack: str, source: str) -> str:
    """The test file Codewright owns for `source` (it is rewritten as a whole on rework; the project's own tests
    stay untouched)."""
    p = Path(source)
    directory = "" if p.parent == Path(".") else f"{p.parent.as_posix()}/"
    return _EXTRA.get(pack, "{dir}{stem}_codewright_test" + p.suffix).format(stem=p.stem, dir=directory)


_TEST_NAME = re.compile(r"(?:func\s+(\w+)|def\s+(\w+)|\b(?:it|test|describe)\(\s*[\"'`]([^\"'`]+))")


def taken_names(work: Path, test_path: str, limit: int = 40) -> list[str]:
    """Function and test names already defined by the other test files in the same folder (the same package for Go
    and C++): a new file that reuses one doesn't compile or silently shadows a test."""
    folder = (work / test_path).parent
    names: list[str] = []
    for f in sorted(folder.glob("*")) if folder.is_dir() else []:
        if f.is_file() and f.name != Path(test_path).name and "test" in f.name.lower():
            text = f.read_text(encoding="utf-8", errors="replace")
            names += [n for m in _TEST_NAME.finditer(text) for n in m.groups() if n]
    return list(dict.fromkeys(names))[:limit]


def naming_rule(work: Path, test_path: str) -> str:
    """Prompt text that keeps a new test file from clashing with the project's own tests."""
    taken = taken_names(work, test_path)
    rule = (
        "\n\nOther test files in the same package exist. Give every test and helper you define a distinctive name "
        "containing 'Codewright' (TestCodewrightXxx, test_codewright_xxx) so nothing clashes."
    )
    return rule + (f" Names already taken, never reuse them: {', '.join(taken)}." if taken else "")


def component_for(work: Path, path: str) -> Component | None:
    """The component (detected by the Language Packs) that owns `path`, the most specific one first."""
    owning = [c for c in detect_project(work) if c.path in (".", path) or path.startswith(f"{c.path}/")]
    return max(owning, key=lambda c: len(c.path), default=None)


def write_file(work: Path, path: str, content: str) -> Path:
    """Writes the complete new content of `path` (relative to `work`), making parent folders as needed. Refuses a
    path that would land outside the workspace (`..`, an absolute path)."""
    target = (work / path).resolve()
    root = work.resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"refusing to write outside the workspace: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    text = content if content.endswith("\n") else content + "\n"
    target.write_text(text, encoding="utf-8")
    return target


def description(inputs: dict[str, Any]) -> str:
    """The user's request plus intake answers, as one block of text an LLM prompt can quote."""
    parts = [str(inputs.get("request", ""))]
    parts += [f"{a[0]}: {a[1]}" for a in inputs.get("answers", []) if isinstance(a, list | tuple) and len(a) == 2]
    return "\n".join(p for p in parts if p.strip())[:2000]


def component_result(results: list[dict[str, Any]], component_path: str) -> dict[str, Any] | None:
    """`project.test()`'s result for one component (its only result, if there was no path to match)."""
    return next((r for r in results if r.get("component") == component_path), results[0] if results else None)


def failure_text(report: dict[str, Any] | None) -> str:
    """The failing/erroring cases of a test report, as feedback for the next Reflection attempt."""
    if not report:
        return "no test report"
    cases = report.get("cases") or []
    bad = [c for c in cases if c.get("status") in ("failed", "error")]
    if not bad and report.get("found") is False:
        return "the test tool produced no report (it may not have run at all)"
    lines = [f"{c['name']}: {c.get('message', '')[:250]}" for c in bad[:6]]
    return "\n".join(lines)[:MAX_FAILURE_CHARS] or "all tests passed"


_KEY_LINE = re.compile(r"assert|error|fail|expected|panic|exception|undefined|not declared", re.IGNORECASE)


def _key_lines(output: str) -> str:
    """The lines of a failed step's output that say what broke (assertions, compiler errors) ahead of its tail, so
    a long build log can't push them out of the model's small context."""
    lines = output.splitlines()
    key = [ln.strip() for ln in lines if _KEY_LINE.search(ln)][:10]
    return ("\n".join(key) + "\n---\n" if key else "") + output[-(MAX_FAILURE_CHARS // 2) :]


def result_failure(result: dict[str, Any] | None) -> str:
    """Why a `project.test()` result isn't green, for the model that has to fix it: the failing cases, then the lines
    of the broken step's output that say what went wrong (a compile error, a missing module, an assertion) — the
    report is empty, or just "build failed", exactly when the tests never got to run."""
    if not result:
        return "the tests did not run"
    cases = failure_text(result.get("report"))
    broken = [s for s in result.get("steps", []) if not s.get("ok", s.get("exit_code") == 0)]
    output = _key_lines(broken[-1].get("output_tail") or "") if broken else ""
    parts = [result.get("error") or "", cases if cases != "no test report" else "", output]
    return "\n---\n".join(p for p in parts if p)[: MAX_FAILURE_CHARS + 600] or cases


def is_green(report: dict[str, Any] | None) -> bool:
    return bool(report and report.get("ok"))


def strip_fences(text: str) -> str:
    """A model's answer, stripped of the one fenced code block it was asked for (its language tag, if any, too)."""
    text = text.strip()
    if text.startswith("```"):
        after_open = text.find("\n")
        if after_open != -1:
            text = text[after_open + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip() + "\n"
