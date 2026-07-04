"""Hourly rollup job — pre-compute snapshot tables for the public index."""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import (
    AvailabilityDailyRollup,
    AvailabilityObservation,
    AvailabilityStatus,
    GpuIndexSnapshot,
    GpuType,
    PriceHistoryPoint,
    PriceObservation,
    Provider,
    ProviderGpuSnapshot,
    RollupRun,
)

logger = logging.getLogger(__name__)

HISTORY_DAYS = 30
AVAILABILITY_DAYS = 7


def availability_indicator(rate: float | None) -> str:
    if rate is None:
        return "unknown"
    if rate >= 0.7:
        return "green"
    if rate >= 0.3:
        return "yellow"
    return "red"


def _hour_bucket(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _day_bucket(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    d = dt.astimezone(UTC).date()
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def compute_rollups(session: Session) -> RollupRun:
    """Compute all snapshot tables from raw observations."""
    started_at = datetime.now(UTC)
    snapshot_at = started_at.replace(minute=0, second=0, microsecond=0)

    existing = (
        session.query(RollupRun)
        .filter_by(snapshot_at=snapshot_at, status="success")
        .one_or_none()
    )
    if existing:
        return existing

    session.query(RollupRun).filter_by(snapshot_at=snapshot_at).delete()
    session.query(GpuIndexSnapshot).filter_by(snapshot_at=snapshot_at).delete()
    session.query(PriceHistoryPoint).filter_by(snapshot_at=snapshot_at).delete()
    session.query(ProviderGpuSnapshot).filter_by(snapshot_at=snapshot_at).delete()
    session.query(AvailabilityDailyRollup).filter_by(snapshot_at=snapshot_at).delete()

    run = RollupRun(
        snapshot_at=snapshot_at,
        started_at=started_at,
        status="running",
    )
    session.add(run)
    session.flush()

    try:
        gpu_types = session.query(GpuType).order_by(GpuType.name).all()
        gpu_ids_with_prices = {
            row[0]
            for row in session.query(PriceObservation.gpu_type_id)
            .distinct()
            .all()
        }
        active_gpus = [g for g in gpu_types if g.id in gpu_ids_with_prices]

        avail_rates = _compute_availability_rates(session, hours=24)
        avail_by_provider = _compute_provider_availability_rates(session, hours=24)
        daily_avail = _compute_daily_availability(session, days=AVAILABILITY_DAYS)

        index_rows = 0
        provider_rows = 0
        history_rows = 0
        daily_rows = 0

        for gpu in active_gpus:
            latest_prices = _latest_prices(session, gpu.id, hours=24)
            if not latest_prices:
                continue

            listed_prices = [p["price_per_gpu_hour"] for p in latest_prices]
            providers = {p["provider_id"] for p in latest_prices}

            available_prices = [
                p["price_per_gpu_hour"]
                for p in latest_prices
                if avail_by_provider.get((gpu.id, p["provider_id"], p["region"]), 0) >= 0.5
            ]

            gpu_avail_rate = avail_rates.get(gpu.id)
            session.add(
                GpuIndexSnapshot(
                    snapshot_at=snapshot_at,
                    gpu_type_id=gpu.id,
                    cheapest_listed_per_gpu_hour_usd=min(listed_prices),
                    cheapest_available_per_gpu_hour_usd=min(available_prices)
                    if available_prices
                    else None,
                    provider_count=len(providers),
                    availability_rate_24h=gpu_avail_rate,
                    availability_indicator=availability_indicator(gpu_avail_rate),
                )
            )
            index_rows += 1

            # Provider comparison — cheapest row per provider
            by_provider: dict[int, dict[str, Any]] = {}
            for p in latest_prices:
                pid = p["provider_id"]
                if pid not in by_provider or p["price_per_gpu_hour"] < by_provider[pid]["price_per_gpu_hour"]:
                    by_provider[pid] = p

            for p in by_provider.values():
                rate = avail_by_provider.get((gpu.id, p["provider_id"], p["region"]))
                session.add(
                    ProviderGpuSnapshot(
                        snapshot_at=snapshot_at,
                        gpu_type_id=gpu.id,
                        provider_id=p["provider_id"],
                        region=p["region"],
                        billing_kind=p["billing_kind"],
                        price_per_gpu_hour_usd=p["price_per_gpu_hour"],
                        availability_rate_24h=rate,
                        availability_indicator=availability_indicator(rate),
                    )
                )
                provider_rows += 1

            history_rows += _compute_price_history(session, gpu.id, snapshot_at)

        for (gpu_id, provider_id, day), stats in daily_avail.items():
            session.add(
                AvailabilityDailyRollup(
                    snapshot_at=snapshot_at,
                    gpu_type_id=gpu_id,
                    provider_id=provider_id,
                    day=day,
                    availability_rate=stats["rate"],
                    poll_count=stats["count"],
                )
            )
            daily_rows += 1

        run.status = "success"
        run.gpu_index_rows = index_rows
        run.provider_snapshot_rows = provider_rows
        run.price_history_rows = history_rows
        run.availability_daily_rows = daily_rows
        run.finished_at = datetime.now(UTC)
        session.flush()
        return run
    except Exception as exc:
        run.status = "error"
        run.error_message = str(exc)[:2000]
        run.finished_at = datetime.now(UTC)
        session.flush()
        raise


def _latest_prices(session: Session, gpu_type_id: int, hours: int) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    subq = (
        session.query(
            PriceObservation.provider_id,
            PriceObservation.region,
            PriceObservation.instance_sku,
            PriceObservation.billing_kind,
            func.max(PriceObservation.observed_at).label("max_at"),
        )
        .filter(
            PriceObservation.gpu_type_id == gpu_type_id,
            PriceObservation.observed_at >= since,
        )
        .group_by(
            PriceObservation.provider_id,
            PriceObservation.region,
            PriceObservation.instance_sku,
            PriceObservation.billing_kind,
        )
        .subquery()
    )

    rows = (
        session.query(
            PriceObservation.provider_id,
            PriceObservation.region,
            PriceObservation.billing_kind,
            PriceObservation.price_per_gpu_hour_usd,
        )
        .join(
            subq,
            (PriceObservation.provider_id == subq.c.provider_id)
            & (PriceObservation.region == subq.c.region)
            & (PriceObservation.instance_sku == subq.c.instance_sku)
            & (PriceObservation.billing_kind == subq.c.billing_kind)
            & (PriceObservation.observed_at == subq.c.max_at),
        )
        .filter(PriceObservation.gpu_type_id == gpu_type_id)
        .all()
    )
    return [
        {
            "provider_id": r.provider_id,
            "region": r.region,
            "billing_kind": r.billing_kind,
            "price_per_gpu_hour": r.price_per_gpu_hour_usd,
        }
        for r in rows
    ]


def _compute_availability_rates(session: Session, hours: int) -> dict[int, float]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        session.query(
            AvailabilityObservation.gpu_type_id,
            AvailabilityObservation.status,
            func.count().label("cnt"),
        )
        .filter(AvailabilityObservation.observed_at >= since)
        .group_by(
            AvailabilityObservation.gpu_type_id,
            AvailabilityObservation.status,
        )
        .all()
    )
    totals: dict[int, int] = defaultdict(int)
    available: dict[int, int] = defaultdict(int)
    for gpu_id, status, cnt in rows:
        totals[gpu_id] += cnt
        if status == AvailabilityStatus.AVAILABLE.value:
            available[gpu_id] += cnt
    return {
        gpu_id: available[gpu_id] / totals[gpu_id]
        for gpu_id in totals
        if totals[gpu_id] > 0
    }


def _compute_provider_availability_rates(
    session: Session, hours: int
) -> dict[tuple[int, int, str], float]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        session.query(
            AvailabilityObservation.gpu_type_id,
            AvailabilityObservation.provider_id,
            AvailabilityObservation.region,
            AvailabilityObservation.status,
            func.count().label("cnt"),
        )
        .filter(AvailabilityObservation.observed_at >= since)
        .group_by(
            AvailabilityObservation.gpu_type_id,
            AvailabilityObservation.provider_id,
            AvailabilityObservation.region,
            AvailabilityObservation.status,
        )
        .all()
    )
    totals: dict[tuple[int, int, str], int] = defaultdict(int)
    available: dict[tuple[int, int, str], int] = defaultdict(int)
    for gpu_id, provider_id, region, status, cnt in rows:
        key = (gpu_id, provider_id, region)
        totals[key] += cnt
        if status == AvailabilityStatus.AVAILABLE.value:
            available[key] += cnt
    return {
        key: available[key] / totals[key]
        for key in totals
        if totals[key] > 0
    }


def _compute_daily_availability(
    session: Session, days: int
) -> dict[tuple[int, int, datetime], dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        session.query(
            AvailabilityObservation.gpu_type_id,
            AvailabilityObservation.provider_id,
            AvailabilityObservation.observed_at,
            AvailabilityObservation.status,
        )
        .filter(AvailabilityObservation.observed_at >= since)
        .all()
    )
    buckets: dict[tuple[int, int, datetime], list[bool]] = defaultdict(list)
    for gpu_id, provider_id, observed_at, status in rows:
        day = _day_bucket(observed_at)
        buckets[(gpu_id, provider_id, day)].append(
            status == AvailabilityStatus.AVAILABLE.value
        )

    result: dict[tuple[int, int, datetime], dict[str, Any]] = {}
    for key, values in buckets.items():
        result[key] = {
            "rate": sum(values) / len(values) if values else None,
            "count": len(values),
        }
    return result


def _compute_price_history(
    session: Session, gpu_type_id: int, snapshot_at: datetime
) -> int:
    since = datetime.now(UTC) - timedelta(days=HISTORY_DAYS)
    rows = (
        session.query(
            PriceObservation.observed_at,
            PriceObservation.price_per_gpu_hour_usd,
            PriceObservation.provider_id,
        )
        .filter(
            PriceObservation.gpu_type_id == gpu_type_id,
            PriceObservation.observed_at >= since,
        )
        .all()
    )
    if not rows:
        return 0

    by_hour: dict[datetime, list[float]] = defaultdict(list)
    providers_by_hour: dict[datetime, set[int]] = defaultdict(set)
    for observed_at, price, provider_id in rows:
        bucket = _hour_bucket(observed_at)
        by_hour[bucket].append(price)
        providers_by_hour[bucket].add(provider_id)

    count = 0
    for bucket, prices in sorted(by_hour.items()):
        session.add(
            PriceHistoryPoint(
                snapshot_at=snapshot_at,
                gpu_type_id=gpu_type_id,
                hour_bucket=bucket,
                min_per_gpu_hour_usd=min(prices),
                median_per_gpu_hour_usd=float(statistics.median(prices)),
                max_per_gpu_hour_usd=max(prices),
                provider_count=len(providers_by_hour[bucket]),
            )
        )
        count += 1
    return count


def latest_snapshot_at(session: Session) -> datetime | None:
    row = (
        session.query(RollupRun.snapshot_at)
        .filter(RollupRun.status == "success")
        .order_by(RollupRun.snapshot_at.desc())
        .first()
    )
    return row[0] if row else None
