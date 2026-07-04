"""Initial schema — providers, observations, heartbeats."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("api_type", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "gpu_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("vram_gb", sa.Integer(), nullable=True),
        sa.Column("architecture", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "price_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("gpu_type_id", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("instance_sku", sa.String(length=256), nullable=False),
        sa.Column("gpu_count", sa.Integer(), nullable=False),
        sa.Column("vcpus", sa.Integer(), nullable=True),
        sa.Column("ram_gb", sa.Float(), nullable=True),
        sa.Column("price_hourly_usd", sa.Float(), nullable=False),
        sa.Column("price_per_gpu_hour_usd", sa.Float(), nullable=False),
        sa.Column("billing_kind", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["gpu_type_id"], ["gpu_types.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_price_obs_provider_gpu_region_time",
        "price_observations",
        ["provider_id", "gpu_type_id", "region", "observed_at"],
    )
    op.create_table(
        "availability_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("gpu_type_id", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("instance_sku", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("probe_method", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["gpu_type_id"], ["gpu_types.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_avail_obs_provider_gpu_region_time",
        "availability_observations",
        ["provider_id", "gpu_type_id", "region", "observed_at"],
    )
    op.create_table(
        "canary_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("gpu_type_id", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=32), nullable=True),
        sa.Column("provision_latency_s", sa.Float(), nullable=True),
        sa.Column("advertised_price", sa.Float(), nullable=True),
        sa.Column("billed_price", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["gpu_type_id"], ["gpu_types.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "raw_payloads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("collector_name", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_gzip", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "collector_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("collector_name", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("price_rows_written", sa.Integer(), nullable=True),
        sa.Column("availability_rows_written", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_collector_runs_collector_name",
        "collector_runs",
        ["collector_name"],
    )
    op.create_table(
        "scheduler_heartbeats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=256), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("scheduler_heartbeats")
    op.drop_index("ix_collector_runs_collector_name", table_name="collector_runs")
    op.drop_table("collector_runs")
    op.drop_table("raw_payloads")
    op.drop_table("canary_runs")
    op.drop_index("ix_avail_obs_provider_gpu_region_time", table_name="availability_observations")
    op.drop_table("availability_observations")
    op.drop_index("ix_price_obs_provider_gpu_region_time", table_name="price_observations")
    op.drop_table("price_observations")
    op.drop_table("gpu_types")
    op.drop_table("providers")
