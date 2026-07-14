"""Tests for public API and pages."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from analysis.rollups import compute_rollups
from api.deps import get_db
from api.main import app
from collectors.parser_version import CURRENT_PARSER_VERSION
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
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

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
    compute_rollups(session)
    session.commit()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    session.close()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_api_index(client):
    resp = client.get("/api/v1/index")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data_license"] == "CC BY 4.0"
    assert "generated_at" in data
    assert data["methodology_url"] == "/methodology"
    assert len(data["gpus"]) == 1
    gpu = data["gpus"][0]
    assert gpu["gpu"] == "H100-SXM-80GB"
    assert gpu["billing_kind"] == "on_demand"
    assert gpu["median_on_demand_per_gpu_hour_usd"] == 3.0
    assert "sparkline" in gpu
    assert "insufficient_data" in gpu


def test_api_prices(client):
    resp = client.get("/api/v1/prices", params={"gpu": "H100-SXM-80GB"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["gpu"] == "H100-SXM-80GB"
    assert len(data["providers"]) == 1


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "H100-SXM-80GB" in resp.text
    assert "gpu-card" in resp.text
    assert "gpu-grid" in resp.text


def test_index_page_shows_trends_when_history_exists():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    providers = [
        Provider(name=f"Cloud {i}", slug=f"cloud-{i}", kind="neocloud", api_type="rest")
        for i in range(3)
    ]
    gpu = GpuType(name="H100-SXM-80GB", vram_gb=80, architecture="hopper")
    session.add_all([*providers, gpu])
    session.flush()

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    # Enough eligible offers/providers at each lookback so trends are allowed
    price_by_age = {168: 4.0, 24: 3.0, 0: 2.0}
    for hours_ago, price in price_by_age.items():
        for i, provider in enumerate(providers):
            for j in range(2):
                session.add(
                    PriceObservation(
                        provider_id=provider.id,
                        gpu_type_id=gpu.id,
                        region="us-east-1",
                        instance_sku=f"sku-{i}-{j}",
                        gpu_count=1,
                        price_hourly_usd=price,
                        price_per_gpu_hour_usd=price,
                        billing_kind="on_demand",
                        observed_at=now - timedelta(hours=hours_ago),
                        source="api",
                        parser_version=CURRENT_PARSER_VERSION,
                    )
                )
    compute_rollups(session)
    session.commit()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        api = client.get("/api/v1/index").json()["gpus"][0]
        assert len(api["sparkline"]) >= 2
        assert api["insufficient_data"] is False
        assert api["change_24h_pct"] == -33.3
        assert api["change_7d_pct"] == -50.0

        page = client.get("/")
        assert page.status_code == 200
        assert "spark-fill" in page.text
        assert "-33.3%" in page.text
        assert "-50.0%" in page.text
        assert "gpu-card" in page.text
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_methodology_page(client):
    resp = client.get("/methodology")
    assert resp.status_code == 200
    assert "Marketplace eligibility" in resp.text
    assert "0.95" in resp.text
    assert "CC BY 4.0" in resp.text
    assert "marketplace_listing" in resp.text


def test_status_and_robots(client):
    assert client.get("/status").status_code == 200
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Sitemap" in robots.text
    assert client.get("/sitemap.xml").status_code == 200


def test_prices_csv(client):
    resp = client.get("/api/v1/prices.csv", params={"gpu": "H100-SXM-80GB"})
    assert resp.status_code == 200
    assert "median" in resp.text
    assert "text/csv" in resp.headers["content-type"]
