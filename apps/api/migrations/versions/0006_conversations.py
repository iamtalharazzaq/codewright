"""Conversations, messages (a tree, for edit/regenerate/branch) and memory (CODEWRIGHT.md Sections 2.2 and 3.4).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("head_id", sa.Uuid()),  # the last message of the branch being shown
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="CASCADE")),
        sa.Column("role", sa.String(10), nullable=False),
        # text | questions | confirm | run | done | decline | error
        sa.Column("kind", sa.String(20), nullable=False, server_default="text"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        # complete | streaming | stopped | error
        sa.Column("status", sa.String(20), nullable=False, server_default="complete"),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_parent_id", "messages", ["parent_id"])

    op.add_column(
        "runs", sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"))
    )

    op.create_table(
        "memory_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE")),  # None: user memory
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source", sa.String(40), nullable=False, server_default="chat"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "project_id", "key", name="uq_memory_items_project_key", postgresql_nulls_not_distinct=True
        ),
    )


def downgrade() -> None:
    op.drop_table("memory_items")
    op.drop_column("runs", "conversation_id")
    op.drop_table("messages")
    op.drop_table("conversations")
