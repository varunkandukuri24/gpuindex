"""Public JSON API v1 — reads pre-computed rollup tables only."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from analysis.rollups import latest_snapshot_at
from analysis.trends import build_index_trends
from api.deps import get_db
from db.models import (
    AvailabilityDailyRollup,
    GpuIndexSnapshot,
    GpuType,
    PriceHistoryPoint,
    Provider,
    ProviderGpuSnapshot,
)

router = APIRouter(prefix="/api/v1", tags=["v1"])


def _require_snapshot(session: Session) -> datetime:
    snapshot_at = latest_snapshot_at(session)
    if snapshot_at is None:
        raise HTTPException(status_code=503, detail="No snapshot data yet. Rollups pending.")
    return snapshot_at


@router.get("/meta")
def meta(session: Session = Depends(get_db)) -> dict:
    snapshot_at = latest_snapshot_at(session)
    return {
        "snapshot_at": snapshot_at.isoformat() if snapshot_at else None,
        "stale_after_hours": 1,
    }


@router.get("/index")
def index(
    session: Session = Depends(get_db),
    provider_kind: str | None = Query(None),
    billing_kind: str | None = Query(None),
) -> dict:
    snapshot_at = _require_snapshot(session)
    rows = (
        session.query(GpuIndexSnapshot, GpuType)
        .join(GpuType, GpuIndexSnapshot.gpu_type_id == GpuType.id)
        .filter(GpuIndexSnapshot.snapshot_at == snapshot_at)
        .order_by(GpuType.name)
        .all()
    )
    trends = build_index_trends(session, snapshot_at)

    items = []
    for snap, gpu in rows:
        trend = trends.get(gpu.id, {})
        items.append(
            {
                "gpu": gpu.name,
                "vram_gb": gpu.vram_gb,
                "architecture": gpu.architecture,
                "cheapest_listed_per_gpu_hour_usd": snap.cheapest_listed_per_gpu_hour_usd,
                "cheapest_available_per_gpu_hour_usd": snap.cheapest_available_per_gpu_hour_usd,
                "provider_count": snap.provider_count,
                "availability_rate_24h": snap.availability_rate_24h,
                "availability_indicator": snap.availability_indicator,
                "sparkline": trend.get("sparkline", []),
                "change_24h_pct": trend.get("change_24h_pct"),
                "change_7d_pct": trend.get("change_7d_pct"),
            }
        )

    return {"snapshot_at": snapshot_at.isoformat(), "gpus": items}


@router.get("/prices")
def prices(
    gpu: str = Query(..., description="Canonical GPU name"),
    session: Session = Depends(get_db),
) -> dict:
    snapshot_at = _require_snapshot(session)
    gpu_type = session.query(GpuType).filter_by(name=gpu).one_or_none()
    if gpu_type is None:
        raise HTTPException(status_code=404, detail=f"Unknown GPU: {gpu}")

    providers = (
        session.query(ProviderGpuSnapshot, Provider)
        .join(Provider, ProviderGpuSnapshot.provider_id == Provider.id)
        .filter(
            ProviderGpuSnapshot.snapshot_at == snapshot_at,
            ProviderGpuSnapshot.gpu_type_id == gpu_type.id,
        )
        .order_by(ProviderGpuSnapshot.price_per_gpu_hour_usd)
        .all()
    )

    history = (
        session.query(PriceHistoryPoint)
        .filter(
            PriceHistoryPoint.snapshot_at == snapshot_at,
            PriceHistoryPoint.gpu_type_id == gpu_type.id,
        )
        .order_by(PriceHistoryPoint.hour_bucket)
        .all()
    )

    return {
        "snapshot_at": snapshot_at.isoformat(),
        "gpu": gpu,
        "providers": [
            {
                "provider": prov.slug,
                "provider_name": prov.name,
                "provider_kind": prov.kind,
                "region": snap.region,
                "billing_kind": snap.billing_kind,
                "price_per_gpu_hour_usd": snap.price_per_gpu_hour_usd,
                "availability_rate_24h": snap.availability_rate_24h,
                "availability_indicator": snap.availability_indicator,
            }
            for snap, prov in providers
        ],
        "history": [
            {
                "hour": h.hour_bucket.astimezone(UTC).isoformat(),
                "min": h.min_per_gpu_hour_usd,
                "median": h.median_per_gpu_hour_usd,
                "max": h.max_per_gpu_hour_usd,
                "provider_count": h.provider_count,
            }
            for h in history
        ],
    }


@router.get("/availability")
def availability(
    gpu: str = Query(...),
    session: Session = Depends(get_db),
) -> dict:
    snapshot_at = _require_snapshot(session)
    gpu_type = session.query(GpuType).filter_by(name=gpu).one_or_none()
    if gpu_type is None:
        raise HTTPException(status_code=404, detail=f"Unknown GPU: {gpu}")

    rows = (
        session.query(AvailabilityDailyRollup, Provider)
        .join(Provider, AvailabilityDailyRollup.provider_id == Provider.id)
        .filter(
            AvailabilityDailyRollup.snapshot_at == snapshot_at,
            AvailabilityDailyRollup.gpu_type_id == gpu_type.id,
        )
        .order_by(AvailabilityDailyRollup.day, Provider.slug)
        .all()
    )

    return {
        "snapshot_at": snapshot_at.isoformat(),
        "gpu": gpu,
        "daily": [
            {
                "provider": prov.slug,
                "day": roll.day.date().isoformat(),
                "availability_rate": roll.availability_rate,
                "poll_count": roll.poll_count,
            }
            for roll, prov in rows
        ],
    }
