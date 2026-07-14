"""Alembic migration — parser_version, attrs, robust rollup columns."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "003_credibility"
down_revision = "002_snapshot_rollups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("price_observations") as batch:
        batch.add_column(
            sa.Column(
                "parser_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch.add_column(sa.Column("attrs_json", sa.Text(), nullable=True))

    with op.batch_alter_table("gpu_index_snapshots") as batch:
        batch.add_column(sa.Column("median_on_demand_per_gpu_hour_usd", sa.Float()))
        batch.add_column(sa.Column("floor_on_demand_per_gpu_hour_usd", sa.Float()))
        batch.add_column(sa.Column("spot_floor_per_gpu_hour_usd", sa.Float()))
        batch.add_column(
            sa.Column("eligible_offer_count", sa.Integer(), server_default="0")
        )
        batch.add_column(
            sa.Column("eligible_provider_count", sa.Integer(), server_default="0")
        )
        batch.add_column(
            sa.Column("trend_sample_ok", sa.Boolean(), server_default="0")
        )

    with op.batch_alter_table("price_history_points") as batch:
        batch.add_column(
            sa.Column(
                "billing_kind",
                sa.String(length=32),
                nullable=False,
                server_default="on_demand",
            )
        )
        batch.add_column(sa.Column("p10_per_gpu_hour_usd", sa.Float()))
        batch.add_column(sa.Column("p90_per_gpu_hour_usd", sa.Float()))
        batch.add_column(
            sa.Column("eligible_offer_count", sa.Integer(), server_default="0")
        )

    with op.batch_alter_table("provider_gpu_snapshots") as batch:
        batch.add_column(sa.Column("probe_method", sa.String(length=32)))
        batch.add_column(sa.Column("last_probed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("attrs_json", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("provider_gpu_snapshots") as batch:
        batch.drop_column("attrs_json")
        batch.drop_column("last_probed_at")
        batch.drop_column("probe_method")

    with op.batch_alter_table("price_history_points") as batch:
        batch.drop_column("eligible_offer_count")
        batch.drop_column("p90_per_gpu_hour_usd")
        batch.drop_column("p10_per_gpu_hour_usd")
        batch.drop_column("billing_kind")

    with op.batch_alter_table("gpu_index_snapshots") as batch:
        batch.drop_column("trend_sample_ok")
        batch.drop_column("eligible_provider_count")
        batch.drop_column("eligible_offer_count")
        batch.drop_column("spot_floor_per_gpu_hour_usd")
        batch.drop_column("floor_on_demand_per_gpu_hour_usd")
        batch.drop_column("median_on_demand_per_gpu_hour_usd")

    with op.batch_alter_table("price_observations") as batch:
        batch.drop_column("attrs_json")
        batch.drop_column("parser_version")
