"""Projects get a source, instructions, a summary and secret-scan findings; chat uploads (CODEWRIGHT.md Phase 3).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # source: {"kind": "zip" | "github" | "local" | "drive" | "empty", "ref": url / path / file name}
    op.add_column("projects", sa.Column("source", JSONB(), nullable=False, server_default="{}"))
    op.add_column("projects", sa.Column("instructions", sa.Text(), nullable=False, server_default=""))
    op.add_column("projects", sa.Column("summary", JSONB(), nullable=False, server_default="{}"))
    op.add_column("projects", sa.Column("secrets", JSONB(), nullable=False, server_default="[]"))
    op.add_column("projects", sa.Column("error", sa.Text()))

    op.create_table(
        "uploads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE")),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),  # text | image | archive | other
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("secrets", JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("uploads")
    for column in ("error", "secrets", "summary", "instructions", "source"):
        op.drop_column("projects", column)
