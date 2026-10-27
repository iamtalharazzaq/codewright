"""Code search (CODEWRIGHT.md Phase 4): split project files into chunks, embed them when an embedding server is
available, and find the chunks that answer a question.

Search is hybrid: vector similarity when chunks have embeddings, otherwise (or additionally) Postgres full-text
search, so it works before the embedding server is set up. Secrets are masked before anything is stored.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from agent.knowledge_graph import module_of
from agent.tools.secrets import MAX_SCAN_BYTES, TEXT_SUFFIX_DENY, mask

log = logging.getLogger(__name__)

CHUNK_LINES = 60
MAX_CHUNKS = 20_000
CODE_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".cpp", ".cc", ".cxx", ".hpp", ".h", ".c", ".java", ".kt",
    ".cs", ".php", ".rb", ".rs", ".swift", ".sql", ".proto", ".graphql", ".yaml", ".yml", ".toml", ".json", ".md",
    ".html", ".css", ".scss", ".vue", ".svelte", ".sh", ".mod",
}  # fmt: skip
SPECIAL_FILES = {"Dockerfile", "Makefile", "docker-compose.yml", "docker-compose.yaml"}


@dataclass(frozen=True)
class Chunk:
    path: str
    start_line: int
    end_line: int
    content: str


def _files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if module_of(rel) is None or not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() in TEXT_SUFFIX_DENY or path.stat().st_size > MAX_SCAN_BYTES:
            continue
        if path.suffix.lower() in CODE_SUFFIXES or path.name in SPECIAL_FILES:
            yield path


def chunk_tree(root: Path, lines: int = CHUNK_LINES) -> list[Chunk]:
    """Chunks of `lines` lines (blank-only chunks skipped), with the path as a header so search sees it."""
    chunks: list[Chunk] = []
    for path in _files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rows = mask(text).splitlines()
        rel = str(path.relative_to(root))
        for start in range(0, len(rows), lines):
            body = "\n".join(rows[start : start + lines])
            if body.strip():
                chunks.append(Chunk(rel, start + 1, min(start + lines, len(rows)), body))
            if len(chunks) >= MAX_CHUNKS:
                return chunks
    return chunks


class Embedder:
    """OpenAI-compatible `/embeddings` (llama.cpp, Ollama). `available` turns False after a failure, so a missing
    server costs one quick try per index, not one per chunk."""

    def __init__(self, base_url: str | None, model: str, dimensions: int, timeout: float = 30) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout
        self.available = base_url is not None

    async def embed(self, texts: Sequence[str]) -> list[list[float]] | None:
        if not self.available or not texts or self.base_url is None:
            return None
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=3)) as client:
                res = await client.post(
                    f"{self.base_url}/embeddings", json={"model": self.model, "input": [t[:4000] for t in texts]}
                )
                res.raise_for_status()
                data = sorted(res.json()["data"], key=lambda d: d["index"])
                vectors: list[list[float]] = [d["embedding"] for d in data]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.info("embeddings unavailable (%s); code search uses full-text only", exc)
            self.available = False
            return None
        if any(len(v) != self.dimensions for v in vectors):
            log.warning("embedding size is not %d; vector search disabled", self.dimensions)
            self.available = False
            return None
        return vectors


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
