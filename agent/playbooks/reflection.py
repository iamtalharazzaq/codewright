"""The Reflection loop (CODEWRIGHT.md Section 7, component 18): failure → hypothesis → fix → retry (max 5) →
escalate. Shared by Write code, Bug fix and Tests: a step that can fail (a test doesn't pass, code doesn't build)
gets a bounded number of attempts, each one told what went wrong last time, before Codewright reports the failure
honestly instead of hiding it or looping forever.

Implemented as a plain loop inside the node that needs it, not as extra graph nodes: each attempt is one call to
`make`, and the budget/recovery bookkeeping of a single LLM call (`agent.playbooks.llm_step`) still applies to
every attempt the same way it would to a single one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

MAX_ATTEMPTS = 5


@dataclass
class Attempt[T]:
    ok: bool
    result: T
    summary: str = ""  # what went wrong, fed back as the next attempt's hint; empty when ok
    update: dict[str, Any] = field(default_factory=dict)  # state deltas to merge in regardless of the outcome


async def reflect[T](
    make: Callable[[int, str | None], Awaitable[Attempt[T]]], max_attempts: int = MAX_ATTEMPTS
) -> tuple[Attempt[T], int]:
    """Calls `make(attempt_no, feedback)` (1-indexed) until it succeeds or `max_attempts` is used up. `feedback` is
    the previous attempt's `summary` (`None` on the first try). Returns the last attempt — the winning one, or the
    final failure to escalate with — and how many tries it took."""
    feedback: str | None = None
    attempt: Attempt[T] | None = None
    for n in range(1, max_attempts + 1):
        attempt = await make(n, feedback)
        if attempt.ok:
            return attempt, n
        feedback = attempt.summary
    assert attempt is not None  # noqa: S101  (max_attempts >= 1)
    return attempt, max_attempts
