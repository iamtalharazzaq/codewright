"""Dependency Auditor (CODEWRIGHT.md Section 5.8): turns each Language Pack's `audit` step output into Findings
that sit next to the Security Engineer's and Secret Scanner's in the same report.

Every tool's own JSON is read tolerantly (a version bump or truncated output must not crash the scan): on anything
unexpected, that tool's output is simply skipped rather than guessed at.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.playbooks.review_core import Finding, Severity

AUDIT_STEPS = {"pip-audit", "npm-audit", "pnpm-audit", "yarn-audit", "govulncheck"}
NPM_SEVERITY: dict[str, Severity] = {"critical": "critical", "high": "major", "moderate": "minor", "low": "nit"}
MANIFEST_CANDIDATES = {
    "python": ("pyproject.toml", "requirements.txt", "setup.py"),
    "node": ("package.json",),
    "go": ("go.mod",),
}


def _json_blob(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else ""


def _manifest_for(work: Path, component: str, pack: str) -> str:
    base = work / component if component != "." else work
    for name in MANIFEST_CANDIDATES.get(pack, ()):
        if (base / name).is_file():
            return f"{component}/{name}" if component != "." else name
    fallback = next(iter(MANIFEST_CANDIDATES.get(pack, ())), "dependencies")
    return f"{component}/{fallback}" if component != "." else fallback


def _pip_audit(output: str, manifest: str) -> list[Finding]:
    try:
        data = json.loads(_json_blob(output) or "{}")
    except ValueError:
        return []
    found = []
    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            fixes = ", ".join(vuln.get("fix_versions", [])[:3])
            msg = f"{dep.get('name')} {dep.get('version')} has a known vulnerability ({vuln.get('id')})" + (
                f"; fixed in {fixes}" if fixes else "; no fixed version yet"
            )
            found.append(
                {"file": manifest, "line": 1, "severity": "major", "category": "security", "problem": msg,
                 "code": f"{dep.get('name')}=={dep.get('version')}", "source": "dependency_auditor"}
            )  # fmt: skip
    return found


def _npm_audit(output: str, manifest: str) -> list[Finding]:
    try:
        data = json.loads(_json_blob(output) or "{}")
    except ValueError:
        return []
    found = []
    for name, v in data.get("vulnerabilities", {}).items():
        severity = NPM_SEVERITY.get(str(v.get("severity", "")), "minor")
        titles = sorted({str(w.get("title")) for w in v.get("via", []) if isinstance(w, dict) and w.get("title")})
        why = "; ".join(titles[:2]) or "a known vulnerability in a transitive dependency"
        found.append(
            {"file": manifest, "line": 1, "severity": severity, "category": "security",
             "problem": f"{name}: {why} (range {v.get('range', '?')})",
             "code": name, "source": "dependency_auditor"}
        )  # fmt: skip
    return found


def _govulncheck(output: str, manifest: str) -> list[Finding]:
    osvs: dict[str, dict[str, Any]] = {}
    for raw in output.splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        osv = item.get("osv")
        if osv and osv.get("id"):
            osvs[osv["id"]] = osv
    found = []
    for oid, osv in osvs.items():
        packages = sorted({a.get("package", {}).get("name", "") for a in osv.get("affected", [])} - {""})
        pkg = packages[0] if packages else "a dependency"
        found.append(
            {"file": manifest, "line": 1, "severity": "major", "category": "security",
             "problem": f"{pkg} has a known vulnerability ({oid}): {osv.get('summary', '').strip()}"[:300],
             "code": pkg, "source": "dependency_auditor"}
        )  # fmt: skip
    return found


_PARSERS = {
    "pip-audit": _pip_audit,
    "npm-audit": _npm_audit,
    "pnpm-audit": _npm_audit,
    "yarn-audit": _npm_audit,
    "govulncheck": _govulncheck,
}


def dependency_findings(outputs: list[dict[str, Any]], work: Path) -> list[Finding]:
    """`outputs` is `project.sandbox("audit", ...)`'s result: one dict per step actually run, across components."""
    found: list[Finding] = []
    seen: set[str] = set()
    for step in outputs:
        parser = _PARSERS.get(str(step.get("step")))
        if parser is None or not step.get("output"):
            continue
        manifest = _manifest_for(work, str(step["component"]), str(step.get("pack", "")))
        for item in parser(step["output"], manifest):
            key = f"{item['file']}:{item['code']}:{item['problem'][:40]}"
            if key not in seen:
                seen.add(key)
                found.append(item)
    return found


def dependency_note(outputs: list[dict[str, Any]]) -> str:
    """Why there are 0 dependency findings: none run, every tool clean, or a tool itself failed."""
    ran = [s for s in outputs if str(s.get("step")) in AUDIT_STEPS]
    if not ran:
        return "no dependency audit tool ran for this project"
    broken = [s["step"] for s in ran if s.get("ok") is False and not _json_blob(s.get("output", ""))]
    return f"{', '.join(broken)} could not run" if broken else "clean"
