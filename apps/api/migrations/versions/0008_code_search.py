"""Code search: chunks of project files with full-text and (when an embedding server is set up) vector search
(CODEWRIGHT.md Phase 4).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1024 = config/models.yaml embeddings.dimensions (Qwen3-Embedding-0.6B). `embedding` stays NULL without a server.
    op.execute(
        """
        CREATE TABLE code_chunks (
            id BIGSERIAL PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            content TEXT NOT NULL,
            tsv TSVECTOR GENERATED ALWAYS AS (
                to_tsvector('simple', regexp_replace(path || ' ' || content, '[_./]', ' ', 'g'))
            ) STORED,
            embedding vector(1024)
        )
        """
    )
    op.execute("CREATE INDEX ix_code_chunks_project ON code_chunks (project_id, path)")
    op.execute("CREATE INDEX ix_code_chunks_tsv ON code_chunks USING GIN (tsv)")


def downgrade() -> None:
    op.execute("DROP TABLE code_chunks")
