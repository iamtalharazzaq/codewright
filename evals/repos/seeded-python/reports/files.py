"""Rendering reports to PDF and serving them."""

import os
import subprocess

REPORT_DIR = "/srv/reports"


def render_pdf(store: str) -> str:
    """Turn the store's Markdown report into a PDF with pandoc; returns the PDF's path."""
    out = os.path.join(REPORT_DIR, f"{store}.pdf")
    subprocess.run(f"pandoc {REPORT_DIR}/{store}.md -o {out}", shell=True, check=True)
    return out


def read_report(name: str) -> bytes:
    """The bytes of a report a member of staff asked for by file name."""
    path = os.path.join(REPORT_DIR, name)
    with open(path, "rb") as f:
        return f.read()
