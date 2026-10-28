"""Outdated direct dependencies, read from each Language Pack's `outdated` step output (CODEWRIGHT.md Section 5.11)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Outdated:
    package: str
    current: str
    latest: str
    component: str
    pack: str

    @property
    def same_major(self) -> bool:
        def major(v: str) -> str:
            return re.sub(r"^\D*", "", v).split(".")[0]

        return major(self.current) == major(self.latest)


def _go(output: str) -> list[tuple[str, str, str]]:
    decoder, pos, found = json.JSONDecoder(), 0, []
    while (start := output.find("{", pos)) != -1:
        try:
            obj, pos = decoder.raw_decode(output, start)
        except ValueError:
            pos = start + 1
            continue
        if obj.get("Main") or obj.get("Indirect") or not obj.get("Update"):
            continue
        found.append((str(obj["Path"]), str(obj.get("Version", "")), str(obj["Update"]["Version"])))
    return found


def _node(output: str) -> list[tuple[str, str, str]]:
    start, end = output.find("{"), output.rfind("}")
    try:
        data = json.loads(output[start : end + 1]) if start != -1 and end > start else {}
    except ValueError:
        return []
    return [
        (name, str(v.get("current", "")), str(v["latest"]))
        for name, v in data.items()
        if isinstance(v, dict) and v.get("current") and v.get("latest")
    ]


def _python(output: str, manifest_text: str) -> list[tuple[str, str, str]]:
    start, end = output.find("["), output.rfind("]")
    try:
        data = json.loads(output[start : end + 1]) if start != -1 and end > start else []
    except ValueError:
        return []
    text = re.sub(r"[-_.]", "-", manifest_text.lower())
    return [
        (str(d["name"]), str(d["version"]), str(d["latest_version"]))
        for d in data
        if isinstance(d, dict) and re.sub(r"[-_.]", "-", str(d.get("name", "")).lower()) in text
    ]


def parse_outdated(pack: str, component: str, output: str, work: Path) -> list[Outdated]:
    base = work / component if component != "." else work
    manifest = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in [*base.glob("requirements*.txt"), base / "pyproject.toml"]
        if p.is_file()
    )
    rows: list[tuple[str, str, str]]
    if pack == "go":
        rows = _go(output)
    elif pack == "node":
        rows = _node(output)
    elif pack == "python":
        rows = _python(output, manifest)
    else:
        rows = []
    return [Outdated(name, cur, new, component, pack) for name, cur, new in rows if cur != new]


def named_in(text: str, items: list[Outdated]) -> list[Outdated]:
    """The outdated packages a request names ("upgrade gin", "bump github.com/gin-gonic/gin")."""
    words = set(re.findall(r"[\w./@-]+", text.lower()))
    hit = []
    for o in items:
        name = o.package.lower()
        if name in words or name.rsplit("/", 1)[-1] in words:
            hit.append(o)
    return hit


def version_in(text: str) -> str | None:
    m = re.search(r"\bv?(\d+\.\d+(?:\.\d+)?)\b", text)
    return m.group(1) if m else None
