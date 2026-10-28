"""Secret scanning and masking (CODEWRIGHT.md Section 11): imports and uploads are scanned; secrets are masked before
text reaches a prompt, a log or a trace.

Pattern-based, so it is fast and has no dependencies. It finds the common credential formats and `key = value`
assignments with secret-looking names; it is a safety net, not a guarantee.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

PATTERNS: dict[str, re.Pattern[str]] = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "GitLab token": re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    "Slack token": re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b"),
    "Stripe key": re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "OpenAI-style key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "password in URL": re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:([^\s:/@]{3,})@"),
    # NAME = "value" where the name looks secret and the value isn't an obvious placeholder.
    "secret assignment": re.compile(
        r"""(?ix)
        \b[\w.-]*(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|token|private[_-]?key)[\w.-]*
        \s*[:=]\s*["']?
        (?!(?:changeme|example|placeholder|your[_-]|xxx|\*\*\*|<|\$\{|\$\(|none|null|true|false|os\.|process\.|env)\b)
        ([^\s"'#,;]{8,})"""
    ),
}

MASK = "«secret»"
# Files never read as text: binary or too big to matter for secrets.
MAX_SCAN_BYTES = 1_000_000
TEXT_SUFFIX_DENY = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".jar", ".so", ".dll"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target", "vendor"}


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    line: int

    def as_dict(self) -> dict[str, str | int]:
        return {"kind": self.kind, "path": self.path, "line": self.line}


# Source code: a secret assignment is only a finding when the value is a string literal. `Password: cfg.DBPassword`
# reads a value from configuration; config files (.env, YAML, INI...) have unquoted values, so they keep the rule.
CODE_SUFFIXES = {
    ".py", ".go", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".java", ".kt", ".cs", ".rb", ".php", ".rs", ".swift",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp",
}  # fmt: skip
# A quoted value made of plain words is a name, not a secret: `TokenType = "x-access"`,
# `TOKEN_KEY = 'app_access_token'` (a storage key). Real secrets are random: digits, mixed case.
_LABEL = re.compile(r"[a-z]+(?:[-_.:][a-z]+)+")


def scan_text(text: str, path: str = "") -> list[Finding]:
    code = Path(path).suffix.lower() in CODE_SUFFIXES
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for kind, pattern in PATTERNS.items():
            m = pattern.search(line)
            if m and code and kind == "secret assignment" and line[m.start(1) - 1 : m.start(1)] not in ("'", '"', "`"):
                continue  # an expression (a variable, a config field, a call), not a hard-coded value
            if m and code and kind == "secret assignment" and _LABEL.fullmatch(m.group(1).rstrip("'\"`)")):
                continue
            if m:
                findings.append(Finding(kind, path, lineno))
                break  # one finding per line is enough
    return findings


def mask(text: str) -> str:
    """Replace every secret with «secret». For assignments only the value is replaced, so the code still reads."""
    for kind, pattern in PATTERNS.items():
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(0).replace(m.group(1), MASK), text)
        elif kind == "private key":
            text = re.sub(
                r"-----BEGIN [A-Z ]*PRIVATE KEY[A-Z ]*-----.*?(?:-----END [A-Z ]*PRIVATE KEY[A-Z ]*-----|\Z)",
                MASK,
                text,
                flags=re.DOTALL,
            )
        else:
            text = pattern.sub(MASK, text)
    return text


def _text_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if (
            path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() not in TEXT_SUFFIX_DENY
            and path.stat().st_size <= MAX_SCAN_BYTES
        ):
            yield path


def scan_tree(root: Path, limit: int = 200) -> list[Finding]:
    """Scan a folder. `.env`-style files count as a finding even when their values look harmless."""
    findings: list[Finding] = []
    for path in _text_files(root):
        rel = str(path.relative_to(root))
        if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
            findings.append(Finding("environment file", rel, 0))
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(scan_text(text, rel))
        if len(findings) >= limit:
            break
    return findings[:limit]
