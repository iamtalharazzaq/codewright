"""Generic runs: any playbook, with or without a project (README Section 9.1).

`runs.options` becomes `runs.inputs` (validated by the playbook), the microservices-only `runs.mode` moves into the
inputs, and `runs.project_id` becomes optional (general requests have no project).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("runs", "options", new_column_name="inputs")
    op.execute("UPDATE runs SET inputs = inputs || jsonb_build_object('mode', mode)")
    op.drop_column("runs", "mode")
    op.alter_column("runs", "project_id", nullable=True)
    op.alter_column("runs", "playbook", server_default=None)
    op.alter_column("runs", "tier", server_default=None)


def downgrade() -> None:
    op.alter_column("runs", "tier", server_default="3")
    op.alter_column("runs", "playbook", server_default="microservices")
    op.execute("DELETE FROM runs WHERE project_id IS NULL")
    op.alter_column("runs", "project_id", nullable=False)
    op.add_column("runs", sa.Column("mode", sa.String(20), nullable=False, server_default="audit"))
    op.execute("UPDATE runs SET mode = COALESCE(inputs->>'mode', 'audit')")
    op.alter_column("runs", "inputs", new_column_name="options")
