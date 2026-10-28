"""Test report readers shared by the packs: JUnit XML (pytest, Vitest, Jest, CTest, GoogleTest) and `go test -json`."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from agent.language_packs.base import TestCase, TestReport

MAX_CASES = 200


def _ordered(cases: list[TestCase]) -> list[TestCase]:
    rank = {"failed": 0, "error": 1, "skipped": 2, "passed": 3}
    return sorted(cases, key=lambda c: rank[c.status])[:MAX_CASES]


def junit(paths: list[Path], tool: str) -> TestReport:
    """One report from any number of JUnit XML files (missing files are ignored)."""
    report = TestReport(tool=tool, found=False)
    cases: list[TestCase] = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "<!DOCTYPE" in text or "<!ENTITY" in text:
            continue  # never expand entities from a file a project's code could have written
        try:
            root = ET.fromstring(text)  # noqa: S314
        except ET.ParseError:
            continue
        report.found = True
        for case in root.iter("testcase"):
            name = case.get("name", "?")
            suite = case.get("classname") or ""
            full = f"{suite}::{name}" if suite else name
            file = case.get("file", "")
            failure = case.find("failure")
            error = case.find("error")
            if failure is not None:
                status, message = "failed", failure.get("message") or (failure.text or "")
            elif error is not None:
                status, message = "error", error.get("message") or (error.text or "")
            elif case.find("skipped") is not None or case.get("status") in {"notrun", "disabled", "skipped"}:
                status, message = "skipped", ""
            else:
                status, message = "passed", ""
            cases.append(TestCase(full, status, message.strip()[:2000], file))  # type: ignore[arg-type]
    count(report, cases)
    return report


def count(report: TestReport, cases: list[TestCase]) -> None:
    for c in cases:
        key = "errors" if c.status == "error" else c.status
        setattr(report, key, getattr(report, key) + 1)
    report.cases = _ordered(cases)


def go_json(output: str) -> TestReport:
    """`go test -json` events → report. Build failures show up as packages that fail without test events."""
    report = TestReport(tool="go test", found=False)
    cases: list[TestCase] = []
    logs: dict[tuple[str, str], list[str]] = {}
    failed_packages: dict[str, list[str]] = {}
    for line in output.splitlines():
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        report.found = True
        action, pkg, test = event.get("Action"), event.get("Package", ""), event.get("Test")
        if action == "output":
            logs.setdefault((pkg, test or ""), []).append(event.get("Output", ""))
        elif test and action in {"pass", "fail", "skip"}:
            if "/" in test and action == "pass":
                continue  # subtests are counted through their parent
            status = {"pass": "passed", "fail": "failed", "skip": "skipped"}[action]
            message = "".join(logs.get((pkg, test), []))[-2000:] if action == "fail" else ""
            cases.append(TestCase(f"{pkg}::{test}", status, message.strip(), pkg))  # type: ignore[arg-type]
        elif not test and action == "fail":
            failed_packages[pkg] = logs.get((pkg, ""), [])
    tested = {c.file for c in cases}
    for pkg, lines in failed_packages.items():
        if pkg not in tested or not any(c.status == "failed" and c.file == pkg for c in cases):
            cases.append(TestCase(f"{pkg} (build)", "error", "".join(lines)[-2000:].strip(), pkg))
    count(report, cases)
    return report
