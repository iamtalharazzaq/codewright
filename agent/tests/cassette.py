"""Cassette-replay LLM client for playbook tests (retrofit, 2026-10-29): record once against the real configured
model, then replay fast and deterministically. `make check` and `make check-sandbox` only ever replay — a missing
cassette fails loudly rather than silently calling a real model. Recording is explicit (`CASSETTE_RECORD=1`) and
needs a real model URL, so it never happens by accident. Mirrors `agent/tests/playbooks/helpers.py::llm_returning`'s
shape (an ordered list of replies, the last one repeats) so tests can swap one for the other.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from agent.llm.client import LLMClient
from agent.llm.config import LLMProfile, ProfileName

CASSETTES = Path(__file__).parent / "cassettes"


class _RecordTransport(httpx.AsyncBaseTransport):
    """Forwards every request to the real model server and appends the (request, response) pair to the cassette
    file on disk as it goes, so a crashed recording run still keeps whatever it got up to that point."""

    def __init__(self, path: Path, bodies: list[dict[str, Any]]) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self._path = path
        self._bodies = bodies
        self._tape: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self._bodies.append(body)
        response = await self._inner.handle_async_request(request)
        raw = await response.aread()
        self._tape.append({"request": body, "response": json.loads(raw)})
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._tape, indent=2), encoding="utf-8")
        return httpx.Response(response.status_code, headers=response.headers, content=raw, request=request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def cassette_llm(name: str, *, profile: ProfileName = "remote_gpu") -> tuple[LLMClient, list[dict[str, Any]]]:
    """Replays `agent/tests/cassettes/<name>.json` in call order (requests recorded so far; the last one repeats if
    the test asks for more than were recorded). With `CASSETTE_RECORD=1`, records a fresh cassette against the real
    model at `CASSETTE_LIVE_URL` (defaults to `LLM_REMOTE_GPU_URL`, the same env var the API container uses)."""
    path = CASSETTES / f"{name}.json"
    bodies: list[dict[str, Any]] = []

    if os.environ.get("CASSETTE_RECORD") == "1":
        base_url = os.environ.get("CASSETTE_LIVE_URL") or os.environ["LLM_REMOTE_GPU_URL"]
        model = os.environ.get("CASSETTE_LIVE_MODEL", "Qwen3.5-9B-Q4_K_M")
        num_ctx = int(os.environ.get("CASSETTE_LIVE_NUM_CTX", "4096"))
        prof = LLMProfile(base_url=base_url, model=model, num_ctx=num_ctx, request_timeout_s=180)
        return LLMClient(profile, prof, transport=_RecordTransport(path, bodies)), bodies

    if not path.exists():
        raise FileNotFoundError(f"no cassette at {path} - set CASSETTE_RECORD=1 and LLM_REMOTE_GPU_URL to record one")
    tape = json.loads(path.read_text(encoding="utf-8"))
    if not tape:
        raise ValueError(f"cassette at {path} is empty")

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        i = min(len(bodies) - 1, len(tape) - 1)
        return httpx.Response(200, json=tape[i]["response"])

    prof = LLMProfile(base_url="http://cassette.invalid/v1", model="m", num_ctx=32768)
    return LLMClient(profile, prof, transport=httpx.MockTransport(handler)), bodies
