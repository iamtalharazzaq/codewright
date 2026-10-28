"""Accessibility checks and the safe automatic fixes for a web frontend (WCAG 2.2 AA), plus the small design layer
the modernize step adds. Pure functions over text; nothing here knows a particular project or framework version.

What is checked is what can be read from source: `lang`, viewport, image alternatives, form-control names, icon-only
buttons, clickable non-controls, removed focus outlines and text/background contrast in one CSS rule. A finding the
code can fix safely is fixed; the rest is reported for a person (contrast of colors set elsewhere, headings, focus
order and screen-reader wording cannot be judged from source).
"""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass
from pathlib import Path

from agent.language_packs.base import walk

SUFFIXES = (".tsx", ".jsx", ".html", ".css")
MARKUP = (".tsx", ".jsx", ".html")
TOKENS_FILE = "codewright-modern.css"
HEX = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


@dataclass
class Finding:
    file: str
    line: int
    rule: str
    wcag: str
    message: str
    fixed: bool = False

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# ── contrast ─────────────────────────────────────────────────────────────────
def rgb(value: str) -> tuple[int, int, int]:
    h = value.lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(color: tuple[int, int, int]) -> float:
    def chan(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(v) for v in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(rgb(a)), luminance(rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def readable(fg: str, bg: str, need: float = 4.5) -> str:
    """`fg` moved in lightness, away from the background, until it reads at `need`:1 (same hue)."""
    r, g, b = (v / 255 for v in rgb(fg))
    h, start, s = colorsys.rgb_to_hls(r, g, b)
    best: tuple[int, str] | None = None
    for step in (-0.02, 0.02):  # darker or lighter, whichever reaches the ratio with the smaller change
        lightness = start
        for n in range(1, 51):
            lightness = min(1.0, max(0.0, lightness + step))
            out = "#%02x%02x%02x" % tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, lightness, s))
            if contrast(out, bg) >= need:
                best = min(best, (n, out)) if best else (n, out)
                break
    return best[1] if best else ("#000000" if luminance(rgb(bg)) > 0.5 else "#ffffff")


RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _css_color(body: str, prop: str) -> re.Match[str] | None:
    return re.search(rf"(?<![-\w]){prop}\s*:\s*#([0-9a-fA-F]{{3}}|[0-9a-fA-F]{{6}})\b", body)


def check_css(path: str, text: str, fix: bool) -> tuple[str, list[Finding]]:
    found: list[Finding] = []
    out = text
    for m in list(RULE.finditer(text)):
        body = m.group(2)
        fg = _css_color(body, "color")
        bg = _css_color(body, "background(?:-color)?")
        if fg and bg:
            ratio = contrast("#" + fg.group(1), "#" + bg.group(1))
            if ratio < 4.5:
                finding = Finding(path, _line(text, m.start()), "contrast", "1.4.3", f"text {ratio:.1f}:1, needs 4.5:1")
                if fix:
                    better = readable("#" + fg.group(1), "#" + bg.group(1))
                    new_body = body[: fg.start()] + fg.group(0).replace("#" + fg.group(1), better) + body[fg.end() :]
                    out = out.replace(m.group(0), m.group(0).replace(body, new_body), 1)
                    finding.fixed = True
                found.append(finding)
        if re.search(r"outline\s*:\s*(?:none|0)\b", body) and re.search(r":focus(?!-visible)", m.group(1)):
            found.append(
                Finding(
                    path,
                    _line(text, m.start()),
                    "focus-outline",
                    "2.4.7",
                    "the focus outline is removed",
                    fixed=fix,  # the design layer's :focus-visible ring replaces it
                )
            )
    return out, found


# ── markup ───────────────────────────────────────────────────────────────────
IMG = re.compile(r"<img\b(?![^>]*\balt\s*=)([^>]*?)(/?)>", re.S)
HTML_TAG = re.compile(r"<html\b(?![^>]*\blang\s*=)([^>]*)>")
INPUT = re.compile(r"<(input|textarea|select)\b([^>]*)>", re.S)
ICON_BUTTON = re.compile(r"<button\b([^>]*)>\s*<(?:svg|img|i)\b[^>]*?(?:/>|>.*?</(?:svg|i)>)?\s*</button>", re.S)
CLICKABLE = re.compile(r"<(div|span)\b([^>]*\bonClick\s*=[^>]*)>", re.S)


def check_markup(path: str, text: str, fix: bool) -> tuple[str, list[Finding]]:  # noqa: PLR0912
    found: list[Finding] = []
    out = text
    for m in IMG.finditer(text):
        found.append(Finding(path, _line(text, m.start()), "img-alt", "1.1.1", "image has no alt text", fixed=fix))
    if fix:
        out = IMG.sub(lambda m: f'<img{m.group(1)} alt=""{m.group(2) and " /"}>', out)
    if path.endswith((".html", "layout.tsx", "layout.jsx")) and HTML_TAG.search(text):
        m = HTML_TAG.search(text)
        assert m
        found.append(Finding(path, _line(text, m.start()), "html-lang", "3.1.1", "<html> has no lang", fixed=fix))
        if fix:
            out = HTML_TAG.sub(lambda m: f'<html lang="en"{m.group(1)}>', out, count=1)
    if path.endswith(".html") and "<head" in text and 'name="viewport"' not in text:
        found.append(
            Finding(path, 1, "viewport", "1.4.10", "no viewport meta, so it will not reflow on phones", fixed=fix)
        )
        if fix:
            out = re.sub(
                r"(<head[^>]*>)",
                r'\1\n    <meta name="viewport" content="width=device-width, initial-scale=1" />',
                out,
                count=1,
            )
    for m in INPUT.finditer(text):
        attrs = m.group(2)
        if re.search(r"type\s*=\s*[\"'](?:hidden|submit|button)[\"']", attrs):
            continue
        if (
            not re.search(r"aria-label|aria-labelledby|\bid\s*=|<label", attrs)
            and "<label" not in text[max(0, m.start() - 200) : m.start()]
        ):
            found.append(Finding(path, _line(text, m.start()), "control-name", "4.1.2", f"<{m.group(1)}> has no label"))
    for m in ICON_BUTTON.finditer(text):
        if not re.search(r"aria-label|aria-labelledby|title\s*=", m.group(1)):
            found.append(Finding(path, _line(text, m.start()), "button-name", "4.1.2", "icon-only button has no name"))
    for m in CLICKABLE.finditer(text):
        if not re.search(r"\brole\s*=", m.group(2)):
            found.append(
                Finding(
                    path,
                    _line(text, m.start()),
                    "clickable",
                    "2.1.1",
                    f"<{m.group(1)}> with onClick is not keyboard-reachable",
                )
            )
    return out, found


def scan(root: Path, *, fix: bool) -> tuple[dict[str, str], list[Finding]]:
    """Check (and with `fix`, repair) the frontend under `root`. Returns {path: new text} for changed files and all
    findings, with `fixed` marking what was repaired. Paths are relative to `root`."""
    changed: dict[str, str] = {}
    found: list[Finding] = []
    for f in walk(root, SUFFIXES, limit=3000):
        rel = f.relative_to(root).as_posix()
        if rel.endswith(TOKENS_FILE):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new, hits = (check_css if f.suffix == ".css" else check_markup)(rel, text, fix)
        found += hits
        if new != text:
            changed[rel] = new
    return changed, found


# ── the design layer ─────────────────────────────────────────────────────────
def tokens_css() -> str:
    """Low-specificity (`:where`) rules, so they improve defaults without overriding the project's own styles."""
    return """/* Added by Codewright: a small design layer. Every rule uses :where(), so your own styles still win. */
:root {
  --cw-bg: #ffffff;
  --cw-text: #1a1a1a;
  --cw-muted: #4d4d4d;
  --cw-accent: #0b5fd6;
  --cw-focus: #0b5fd6;
  --cw-radius: 8px;
  --cw-space: 1rem;
  --cw-font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --cw-bg: #121212;
    --cw-text: #f2f2f2;
    --cw-muted: #c4c4c4;
    --cw-accent: #8ab4ff;
    --cw-focus: #8ab4ff;
  }
}
:where(html) { -webkit-text-size-adjust: 100%; }
:where(body) { font-family: var(--cw-font); line-height: 1.5; color: var(--cw-text); background: var(--cw-bg); }
:where(img, video, svg) { max-width: 100%; height: auto; }
:where(a) { color: var(--cw-accent); text-underline-offset: 0.15em; }
:where(:focus-visible) { outline: 3px solid var(--cw-focus); outline-offset: 2px; }
:where(button, [role="button"], select, input:not([type="checkbox"]):not([type="radio"])) {
  min-height: 24px;
  border-radius: var(--cw-radius);
}
:where(h1, h2, h3, h4) { line-height: 1.25; }
@media (max-width: 40rem) {
  :where(table) { display: block; overflow-x: auto; }
}
@media (prefers-reduced-motion: reduce) {
  :where(*, *::before, *::after) {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
"""
