"""Tests for rollup computation."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from analysis.rollups import compute_rollups, latest_snapshot_at
from collectors.parser_version import CURRENT_PARSER_VERSION
from db.models import (
    AvailabilityObservation,
    AvailabilityStatus,
    Base,
    GpuIndexSnapshot,
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
            parser_version=CURRENT_PARSER_VERSION,
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

    snap = db_session.query(GpuIndexSnapshot).one()
    assert snap.median_on_demand_per_gpu_hour_usd == 3.0
    assert snap.floor_on_demand_per_gpu_hour_usd == 3.0
    assert snap.spot_floor_per_gpu_hour_usd is None
    assert snap.trend_sample_ok is False  # only 1 offer / 1 provider

    snapshot_at = latest_snapshot_at(db_session)
    assert snapshot_at is not None


def test_vast_spot_does_not_set_on_demand_floor(db_session):
    vast = Provider(name="Vast", slug="vast", kind="marketplace", api_type="rest")
    gpu = GpuType(name="H100-SXM-80GB", vram_gb=80, architecture="hopper")
    db_session.add_all([vast, gpu])
    db_session.flush()
    now = datetime.now(UTC)

    # Cheap ineligible spot-ish marketplace row (unverified) — should not set floor
    db_session.add(
        PriceObservation(
            provider_id=vast.id,
            gpu_type_id=gpu.id,
            region="us",
            instance_sku="vast-cheap",
            gpu_count=1,
            price_hourly_usd=0.40,
            price_per_gpu_hour_usd=0.40,
            billing_kind="on_demand",
            observed_at=now,
            source="api",
            parser_version=CURRENT_PARSER_VERSION,
            attrs_json='{"reliability2": 0.5, "verified": false}',
        )
    )
    # Eligible on-demand
    db_session.add(
        PriceObservation(
            provider_id=vast.id,
            gpu_type_id=gpu.id,
            region="us",
            instance_sku="vast-good",
            gpu_count=1,
            price_hourly_usd=2.50,
            price_per_gpu_hour_usd=2.50,
            billing_kind="on_demand",
            observed_at=now,
            source="api",
            parser_version=CURRENT_PARSER_VERSION,
            attrs_json='{"reliability2": 0.99, "verified": true}',
        )
    )
    # Spot floor separate
    db_session.add(
        PriceObservation(
            provider_id=vast.id,
            gpu_type_id=gpu.id,
            region="us",
            instance_sku="vast-spot",
            gpu_count=1,
            price_hourly_usd=1.10,
            price_per_gpu_hour_usd=1.10,
            billing_kind="spot",
            observed_at=now,
            source="api",
            parser_version=CURRENT_PARSER_VERSION,
            attrs_json='{"reliability2": 0.99, "verified": true}',
        )
    )
    db_session.commit()

    compute_rollups(db_session)
    db_session.commit()
    snap = db_session.query(GpuIndexSnapshot).one()
    assert snap.floor_on_demand_per_gpu_hour_usd == 2.50
    assert snap.median_on_demand_per_gpu_hour_usd == 2.50
    assert snap.spot_floor_per_gpu_hour_usd == 1.10
    assert snap.cheapest_listed_per_gpu_hour_usd == 2.50
