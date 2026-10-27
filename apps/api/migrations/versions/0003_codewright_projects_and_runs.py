"""Codewright reconciliation: projects are no longer tied to a microservices mode; runs record their playbook and tier.

A project can now be any codebase (README Section 8.1). Every run belongs to a playbook (Section 5) and has a risk
tier (Section 3.2). `runs.mode` stays as the microservices playbook's variant (conversion | audit) until Phase 1
reshapes the run state.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_projects_mode", "projects", type_="check")
    op.drop_column("projects", "mode")
    op.add_column("runs", sa.Column("playbook", sa.String(40), nullable=False, server_default="microservices"))
    op.add_column("runs", sa.Column("tier", sa.SmallInteger(), nullable=False, server_default="3"))
    op.create_check_constraint("ck_runs_tier", "runs", "tier BETWEEN 0 AND 3")


def downgrade() -> None:
    op.drop_constraint("ck_runs_tier", "runs", type_="check")
    op.drop_column("runs", "tier")
    op.drop_column("runs", "playbook")
    op.add_column("projects", sa.Column("mode", sa.String(20), nullable=False, server_default="audit"))
    op.create_check_constraint("ck_projects_mode", "projects", "mode IN ('conversion', 'audit')")
