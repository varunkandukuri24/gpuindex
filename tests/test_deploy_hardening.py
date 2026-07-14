"""Tests for deploy consistency helpers."""

import logging

from analysis.rollups import _resolve_parser_filter
from api.routes.v1 import _warn_stale_rollup_shape
from collectors.parser_version import CURRENT_PARSER_VERSION
from db.models import GpuIndexSnapshot, GpuType, PriceObservation, Provider
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base


def test_stale_rollup_fingerprint_warns(caplog):
    gpu = GpuType(id=1, name="H100-SXM-80GB")
    snap = GpuIndexSnapshot(
        snapshot_at=__import__("datetime").datetime.now(
            __import__("datetime").UTC
        ),
        gpu_type_id=1,
        cheapest_listed_per_gpu_hour_usd=0.67,
        floor_on_demand_per_gpu_hour_usd=None,
    )
    with caplog.at_level(logging.WARNING):
        assert _warn_stale_rollup_shape([(snap, gpu)]) is True
    assert "stale rollup code" in caplog.text


def test_parser_filter_falls_back_to_max_version():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    provider = Provider(name="X", slug="x", kind="neocloud", api_type="rest")
    gpu = GpuType(name="H100-SXM-80GB", vram_gb=80)
    session.add_all([provider, gpu])
    session.flush()
    session.add(
        PriceObservation(
            provider_id=provider.id,
            gpu_type_id=gpu.id,
            region="us",
            instance_sku="a",
            gpu_count=1,
            price_hourly_usd=1.0,
            price_per_gpu_hour_usd=1.0,
            billing_kind="on_demand",
            observed_at=__import__("datetime").datetime.now(
                __import__("datetime").UTC
            ),
            source="api",
            parser_version=1,
        )
    )
    session.commit()
    assert CURRENT_PARSER_VERSION >= 2
    assert _resolve_parser_filter(session) == 1
    session.close()
