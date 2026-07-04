"""Tests for SQLAlchemy models."""

from sqlalchemy import create_engine, inspect

from db.models import Base


def test_all_tables_defined():
    expected = {
        "providers",
        "gpu_types",
        "price_observations",
        "availability_observations",
        "canary_runs",
        "raw_payloads",
        "collector_runs",
        "scheduler_heartbeats",
        "rollup_runs",
        "gpu_index_snapshots",
        "price_history_points",
        "provider_gpu_snapshots",
        "availability_daily_rollups",
    }
    assert set(Base.metadata.tables.keys()) == expected


def test_migrations_create_all_tables():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "price_observations" in tables
    assert "scheduler_heartbeats" in tables
