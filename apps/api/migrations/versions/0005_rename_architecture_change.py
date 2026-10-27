"""The `microservices` playbook is now `architecture_change` with a `target` input (ADR 0016).

Existing runs keep working: their playbook is renamed and they get `target: microservices`.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE runs SET playbook = 'architecture_change', "
        "inputs = jsonb_build_object('target', 'microservices') || inputs WHERE playbook = 'microservices'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE runs SET playbook = 'microservices', inputs = inputs - 'target' WHERE playbook = 'architecture_change'"
    )
