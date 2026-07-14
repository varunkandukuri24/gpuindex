"""Public JSON API v1 — reads pre-computed rollup tables only."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from analysis.rollups import latest_snapshot_at
from analysis.trends import build_index_trends
from api.deps import get_db
from config import settings
from db.models import (
    AvailabilityDailyRollup,
    GpuIndexSnapshot,
    GpuType,
    PriceHistoryPoint,
    Provider,
    ProviderGpuSnapshot,
)

router = APIRouter(prefix="/api/v1", tags=["v1"])

DATA_LICENSE = "CC BY 4.0"
METHODOLOGY_PATH = "/methodology"


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
        "generated_at": datetime.now(UTC).isoformat(),
        "stale_after_hours": 1,
        "methodology_url": METHODOLOGY_PATH,
        "data_license": DATA_LICENSE,
        "site_title": settings.site_title,
    }


@router.get("/index")
def index(
    session: Session = Depends(get_db),
    provider_kind: str | None = Query(None),
    billing_kind: str | None = Query(None),
) -> dict:
    _ = provider_kind, billing_kind  # reserved filters
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
                # Back-compat: cheapest_listed = eligible on-demand floor (never spot).
                "cheapest_listed_per_gpu_hour_usd": snap.floor_on_demand_per_gpu_hour_usd
                if snap.floor_on_demand_per_gpu_hour_usd is not None
                else snap.cheapest_listed_per_gpu_hour_usd,
                "cheapest_available_per_gpu_hour_usd": snap.cheapest_available_per_gpu_hour_usd,
                "median_on_demand_per_gpu_hour_usd": snap.median_on_demand_per_gpu_hour_usd,
                "floor_on_demand_per_gpu_hour_usd": snap.floor_on_demand_per_gpu_hour_usd,
                "spot_floor_per_gpu_hour_usd": snap.spot_floor_per_gpu_hour_usd,
                "billing_kind": "on_demand",
                "eligible_offer_count": snap.eligible_offer_count,
                "eligible_provider_count": snap.eligible_provider_count,
                "provider_count": snap.provider_count,
                "availability_rate_24h": snap.availability_rate_24h,
                "availability_indicator": snap.availability_indicator,
                "sparkline": trend.get("sparkline", []),
                "change_24h_pct": trend.get("change_24h_pct"),
                "change_7d_pct": trend.get("change_7d_pct"),
                "insufficient_data": trend.get("insufficient_data", False),
            }
        )

    return {
        "snapshot_at": snapshot_at.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology_url": METHODOLOGY_PATH,
        "data_license": DATA_LICENSE,
        "gpus": items,
    }


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
            PriceHistoryPoint.billing_kind == "on_demand",
        )
        .order_by(PriceHistoryPoint.hour_bucket)
        .all()
    )

    return {
        "snapshot_at": snapshot_at.isoformat(),
        "gpu": gpu,
        "billing_kind": "on_demand",
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
                "probe_method": snap.probe_method,
                "last_probed_at": snap.last_probed_at.astimezone(UTC).isoformat()
                if snap.last_probed_at
                else None,
            }
            for snap, prov in providers
        ],
        "history": [
            {
                "hour": h.hour_bucket.astimezone(UTC).isoformat(),
                "billing_kind": h.billing_kind,
                "min": h.min_per_gpu_hour_usd,
                "p10": h.p10_per_gpu_hour_usd,
                "median": h.median_per_gpu_hour_usd,
                "p90": h.p90_per_gpu_hour_usd,
                "max": h.max_per_gpu_hour_usd,
                "provider_count": h.provider_count,
                "eligible_offer_count": h.eligible_offer_count,
            }
            for h in history
        ],
    }


@router.get("/prices.csv")
def prices_csv(
    gpu: str = Query(...),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    """CSV export of rollup history (not raw observations)."""
    snapshot_at = _require_snapshot(session)
    gpu_type = session.query(GpuType).filter_by(name=gpu).one_or_none()
    if gpu_type is None:
        raise HTTPException(status_code=404, detail=f"Unknown GPU: {gpu}")

    history = (
        session.query(PriceHistoryPoint)
        .filter(
            PriceHistoryPoint.snapshot_at == snapshot_at,
            PriceHistoryPoint.gpu_type_id == gpu_type.id,
            PriceHistoryPoint.billing_kind == "on_demand",
        )
        .order_by(PriceHistoryPoint.hour_bucket)
        .all()
    )

    def generate():
        yield "hour,billing_kind,min,p10,median,p90,max,provider_count,eligible_offer_count\n"
        for h in history:
            yield (
                f"{h.hour_bucket.astimezone(UTC).isoformat()},"
                f"{h.billing_kind},"
                f"{h.min_per_gpu_hour_usd},"
                f"{h.p10_per_gpu_hour_usd},"
                f"{h.median_per_gpu_hour_usd},"
                f"{h.p90_per_gpu_hour_usd},"
                f"{h.max_per_gpu_hour_usd},"
                f"{h.provider_count},"
                f"{h.eligible_offer_count}\n"
            )

    filename = f"{gpu}-price-history.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
