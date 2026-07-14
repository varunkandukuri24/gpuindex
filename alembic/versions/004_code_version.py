"""Alembic migration — RollupRun.code_version for split-brain detection."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004_code_version"
down_revision = "003_credibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rollup_runs") as batch:
        batch.add_column(sa.Column("code_version", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("rollup_runs") as batch:
        batch.drop_column("code_version")
