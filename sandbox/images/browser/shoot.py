"""Screenshots of a running web app, and a comparison with earlier ones (CODEWRIGHT.md Phase 7, Section 5.14 parity).

    python /opt/codewright/shoot.py <base url> <pages.json> <out dir> [<baseline dir>]

`pages.json` is a list of paths ("/", "/products"). Each page is opened at 1280x800 once the network is idle and
saved as <out>/<slug>.png. With a baseline folder, each shot is compared with the one of the same name: the share of
pixels that differ by more than a small threshold, and a diff image. The result is written to <out>/result.json.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

THRESHOLD = 24  # per-channel difference below which a pixel counts as the same (anti-aliasing, font hinting)


def slug(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "home"


def compare(a: Path, b: Path, out: Path) -> float:
    first, second = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if first.size != second.size:
        second = second.resize(first.size)
    diff = ImageChops.difference(first, second).convert("L").point(lambda v: 255 if v > THRESHOLD else 0)
    changed = sum(1 for v in diff.getdata() if v)
    diff.save(out)
    return round(changed / (first.size[0] * first.size[1]), 5)


def main() -> None:
    base, pages_file, out = sys.argv[1].rstrip("/"), Path(sys.argv[2]), Path(sys.argv[3])
    baseline = Path(sys.argv[4]) if len(sys.argv) > 4 else None
    out.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-dev-shm-usage", "--no-proxy-server"])
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        for path in json.loads(pages_file.read_text(encoding="utf-8")):
            name = slug(path)
            entry: dict[str, object] = {"path": path, "file": f"{name}.png"}
            try:
                response = page.goto(base + path, wait_until="networkidle", timeout=30_000)
                entry["status"] = response.status if response else None
                page.screenshot(path=str(out / f"{name}.png"))
                before = baseline / f"{name}.png" if baseline is not None else None
                if before is not None and before.is_file():
                    entry["diff_ratio"] = compare(before, out / f"{name}.png", out / f"{name}.diff.png")
                    entry["diff_file"] = f"{name}.diff.png"
            except Exception as e:
                entry["error"] = f"{e.__class__.__name__}: {str(e)[:300]}"
            results.append(entry)
        browser.close()
    (out / "result.json").write_text(json.dumps({"base": base, "pages": results}, indent=1), encoding="utf-8")
    print(json.dumps({"pages": len(results), "errors": sum(1 for r in results if "error" in r)}))


if __name__ == "__main__":
    main()
