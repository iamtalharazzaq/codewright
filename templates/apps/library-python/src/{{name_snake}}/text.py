"""Example module: small, pure, typed functions."""

from __future__ import annotations

import re


def slugify(text: str) -> str:
    """Lower-case `text` and join its words with dashes: 'Hello, World!' -> 'hello-world'."""
    return "-".join(re.findall(r"[a-z0-9]+", text.lower()))


def truncate(text: str, limit: int, ellipsis: str = "…") -> str:
    """Cut `text` to at most `limit` characters, ending with `ellipsis` when something was cut."""
    if limit < len(ellipsis):
        raise ValueError("limit is shorter than the ellipsis")
    if len(text) <= limit:
        return text
    return text[: limit - len(ellipsis)] + ellipsis
