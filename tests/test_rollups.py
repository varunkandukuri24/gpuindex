"""Tests for rollup computation."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from analysis.rollups import compute_rollups, latest_snapshot_at
from db.models import (
    AvailabilityObservation,
    AvailabilityStatus,
    Base,
    GpuType,
    PriceObservation,
    ProbeMethod,
    Provider,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
        session.commit()
    finally:
        session.close()


def _seed_observations(session):
    provider = Provider(
        name="Test Cloud", slug="test-cloud", kind="neocloud", api_type="rest"
    )
    gpu = GpuType(name="H100-SXM-80GB", vram_gb=80, architecture="hopper")
    session.add_all([provider, gpu])
    session.flush()

    now = datetime.now(UTC)
    session.add(
        PriceObservation(
            provider_id=provider.id,
            gpu_type_id=gpu.id,
            region="us-east-1",
            instance_sku="test-h100",
            gpu_count=1,
            price_hourly_usd=3.0,
            price_per_gpu_hour_usd=3.0,
            billing_kind="on_demand",
            observed_at=now,
            source="api",
        )
    )
    session.add(
        AvailabilityObservation(
            provider_id=provider.id,
            gpu_type_id=gpu.id,
            region="us-east-1",
            instance_sku="test-h100",
            status=AvailabilityStatus.AVAILABLE.value,
            probe_method=ProbeMethod.CAPACITY_API.value,
            observed_at=now,
        )
    )
    session.commit()


def test_compute_rollups(db_session):
    _seed_observations(db_session)
    run = compute_rollups(db_session)
    db_session.commit()

    assert run.status == "success"
    assert run.gpu_index_rows == 1
    assert run.provider_snapshot_rows == 1
    assert run.price_history_rows >= 1

    snapshot_at = latest_snapshot_at(db_session)
    assert snapshot_at is not None
