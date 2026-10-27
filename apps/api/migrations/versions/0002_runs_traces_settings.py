"""Runs, run events, approvals, traces and app settings (Phase 1).

LangGraph's checkpoint tables are created by `AsyncPostgresSaver.setup()`, not by Alembic.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="created"),
        sa.Column("llm_profile", sa.String(20), nullable=False),
        sa.Column("options", JSONB(), nullable=False, server_default="{}"),
        sa.Column("current_step", sa.String(40)),
        sa.Column("pending", JSONB()),
        sa.Column("error", sa.Text()),
        *_timestamps(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("mode IN ('conversion', 'audit')", name="ck_runs_mode"),
        sa.CheckConstraint(
            "status IN ('created', 'running', 'waiting', 'completed', 'failed', 'cancelled')", name="ck_runs_status"
        ),
    )
    op.create_index("ix_runs_project_id", "runs", ["project_id"])
    op.create_index("ix_runs_status", "runs", ["status"])

    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("step", sa.String(40)),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        *_timestamps(),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gate", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(100)),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("edits", JSONB(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.CheckConstraint("decision IN ('approve', 'edit', 'reject')", name="ck_approvals_decision"),
    )
    op.create_index("ix_approvals_run_id", "approvals", ["run_id"])

    op.create_table(
        "traces",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE")),
        sa.Column("step", sa.String(40)),
        sa.Column("role", sa.String(40)),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("profile", sa.String(20)),
        sa.Column("model", sa.String(200)),
        sa.Column("input", JSONB()),
        sa.Column("output", sa.Text()),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        *_timestamps(),
    )
    op.create_index("ix_traces_run_id", "traces", ["run_id"])
    op.create_index("ix_traces_created_at", "traces", ["created_at"])

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("traces")
    op.drop_table("approvals")
    op.drop_table("run_events")
    op.drop_table("runs")
