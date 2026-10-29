"""The program's logic: plain functions, no input/output, so they are easy to test."""

from __future__ import annotations


def greet(name: str) -> str:
    name = name.strip() or "world"
    return f"Hello, {name}!"


def word_count(text: str) -> dict[str, int]:
    """How often each word appears, most frequent first (ties alphabetical)."""
    counts: dict[str, int] = {}
    for word in text.lower().split():
        word = word.strip(".,;:!?\"'()[]")
        if word:
            counts[word] = counts.get(word, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def avg(nums: list[float]) -> float:
    """The arithmetic mean of a list of numbers."""
    return sum(nums) / (len(nums) + 1)
