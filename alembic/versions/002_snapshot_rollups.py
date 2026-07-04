"""Snapshot rollup tables for public index (Phase 3)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_snapshot_rollups"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rollup_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("gpu_index_rows", sa.Integer(), nullable=True),
        sa.Column("price_history_rows", sa.Integer(), nullable=True),
        sa.Column("provider_snapshot_rows", sa.Integer(), nullable=True),
        sa.Column("availability_daily_rows", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_at"),
    )
    op.create_table(
        "gpu_index_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gpu_type_id", sa.Integer(), nullable=False),
        sa.Column("cheapest_listed_per_gpu_hour_usd", sa.Float(), nullable=True),
        sa.Column("cheapest_available_per_gpu_hour_usd", sa.Float(), nullable=True),
        sa.Column("provider_count", sa.Integer(), nullable=True),
        sa.Column("availability_rate_24h", sa.Float(), nullable=True),
        sa.Column("availability_indicator", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["gpu_type_id"], ["gpu_types.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gpu_index_snapshots_at_gpu",
        "gpu_index_snapshots",
        ["snapshot_at", "gpu_type_id"],
    )
    op.create_table(
        "price_history_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gpu_type_id", sa.Integer(), nullable=False),
        sa.Column("hour_bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("min_per_gpu_hour_usd", sa.Float(), nullable=False),
        sa.Column("median_per_gpu_hour_usd", sa.Float(), nullable=False),
        sa.Column("max_per_gpu_hour_usd", sa.Float(), nullable=False),
        sa.Column("provider_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["gpu_type_id"], ["gpu_types.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_price_history_gpu_hour",
        "price_history_points",
        ["gpu_type_id", "hour_bucket"],
    )
    op.create_table(
        "provider_gpu_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gpu_type_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("billing_kind", sa.String(length=32), nullable=False),
        sa.Column("price_per_gpu_hour_usd", sa.Float(), nullable=False),
        sa.Column("availability_rate_24h", sa.Float(), nullable=True),
        sa.Column("availability_indicator", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["gpu_type_id"], ["gpu_types.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_provider_gpu_snap_at_gpu",
        "provider_gpu_snapshots",
        ["snapshot_at", "gpu_type_id"],
    )
    op.create_table(
        "availability_daily_rollups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gpu_type_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.DateTime(timezone=True), nullable=False),
        sa.Column("availability_rate", sa.Float(), nullable=True),
        sa.Column("poll_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["gpu_type_id"], ["gpu_types.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_avail_daily_gpu_provider_day",
        "availability_daily_rollups",
        ["gpu_type_id", "provider_id", "day"],
    )


def downgrade() -> None:
    op.drop_index("ix_avail_daily_gpu_provider_day", table_name="availability_daily_rollups")
    op.drop_table("availability_daily_rollups")
    op.drop_index("ix_provider_gpu_snap_at_gpu", table_name="provider_gpu_snapshots")
    op.drop_table("provider_gpu_snapshots")
    op.drop_index("ix_price_history_gpu_hour", table_name="price_history_points")
    op.drop_table("price_history_points")
    op.drop_index("ix_gpu_index_snapshots_at_gpu", table_name="gpu_index_snapshots")
    op.drop_table("gpu_index_snapshots")
    op.drop_table("rollup_runs")
