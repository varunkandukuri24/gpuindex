"""Hourly rollup job — pre-compute snapshot tables for the public index."""

from __future__ import annotations

import json
import logging
import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from analysis.eligibility import (
    MIN_ELIGIBLE_OFFERS_FOR_TREND,
    MIN_ELIGIBLE_PROVIDERS_FOR_TREND,
    is_index_eligible,
)
from collectors.parser_version import CURRENT_PARSER_VERSION
from db.models import (
    AvailabilityDailyRollup,
    AvailabilityObservation,
    AvailabilityStatus,
    BillingKind,
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


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        raise ValueError("empty")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _parse_attrs(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


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
        providers_by_id = {p.id: p for p in session.query(Provider).all()}
        gpu_ids_with_prices = {
            row[0]
            for row in session.query(PriceObservation.gpu_type_id)
            .filter(PriceObservation.parser_version == CURRENT_PARSER_VERSION)
            .distinct()
            .all()
        }
        # Fall back to any prices if no current-parser rows yet (fresh deploy).
        if not gpu_ids_with_prices:
            gpu_ids_with_prices = {
                row[0]
                for row in session.query(PriceObservation.gpu_type_id).distinct().all()
            }
            parser_filter = None
        else:
            parser_filter = CURRENT_PARSER_VERSION

        active_gpus = [g for g in gpu_types if g.id in gpu_ids_with_prices]

        avail_rates = _compute_availability_rates(session, hours=24)
        avail_by_provider = _compute_provider_availability_rates(session, hours=24)
        latest_probe = _latest_probe_info(session, hours=48)
        daily_avail = _compute_daily_availability(session, days=AVAILABILITY_DAYS)

        index_rows = 0
        provider_rows = 0
        history_rows = 0
        daily_rows = 0

        for gpu in active_gpus:
            latest_prices = _latest_prices(session, gpu.id, hours=24, parser_version=parser_filter)
            if not latest_prices:
                continue

            eligible = [
                p
                for p in latest_prices
                if is_index_eligible(
                    provider_slug=providers_by_id[p["provider_id"]].slug
                    if p["provider_id"] in providers_by_id
                    else "",
                    billing_kind=p["billing_kind"],
                    attrs=p["attrs"],
                )
            ]

            on_demand = [
                p
                for p in eligible
                if p["billing_kind"] == BillingKind.ON_DEMAND.value
            ]
            spot = [
                p for p in eligible if p["billing_kind"] == BillingKind.SPOT.value
            ]

            od_prices = [p["price_per_gpu_hour"] for p in on_demand]
            spot_prices = [p["price_per_gpu_hour"] for p in spot]
            available_od = [
                p["price_per_gpu_hour"]
                for p in on_demand
                if avail_by_provider.get((gpu.id, p["provider_id"], p["region"]), 0) >= 0.5
            ]

            floor_od = min(od_prices) if od_prices else None
            median_od = float(statistics.median(od_prices)) if od_prices else None
            spot_floor = min(spot_prices) if spot_prices else None

            # Back-compat: cheapest_listed = on-demand eligible floor (never spot).
            cheapest_listed = floor_od
            cheapest_available = min(available_od) if available_od else None

            eligible_providers = {p["provider_id"] for p in eligible}
            trend_ok = (
                len(on_demand) >= MIN_ELIGIBLE_OFFERS_FOR_TREND
                and len({p["provider_id"] for p in on_demand})
                >= MIN_ELIGIBLE_PROVIDERS_FOR_TREND
            )

            gpu_avail_rate = avail_rates.get(gpu.id)
            session.add(
                GpuIndexSnapshot(
                    snapshot_at=snapshot_at,
                    gpu_type_id=gpu.id,
                    cheapest_listed_per_gpu_hour_usd=cheapest_listed,
                    cheapest_available_per_gpu_hour_usd=cheapest_available,
                    median_on_demand_per_gpu_hour_usd=median_od,
                    floor_on_demand_per_gpu_hour_usd=floor_od,
                    spot_floor_per_gpu_hour_usd=spot_floor,
                    eligible_offer_count=len(on_demand),
                    eligible_provider_count=len({p["provider_id"] for p in on_demand}),
                    trend_sample_ok=trend_ok,
                    provider_count=len(eligible_providers),
                    availability_rate_24h=gpu_avail_rate,
                    availability_indicator=availability_indicator(gpu_avail_rate),
                )
            )
            index_rows += 1

            # Provider comparison — cheapest eligible row per (provider, billing_kind)
            by_key: dict[tuple[int, str], dict[str, Any]] = {}
            for p in eligible:
                key = (p["provider_id"], p["billing_kind"])
                if key not in by_key or p["price_per_gpu_hour"] < by_key[key]["price_per_gpu_hour"]:
                    by_key[key] = p

            for p in by_key.values():
                rate = avail_by_provider.get((gpu.id, p["provider_id"], p["region"]))
                probe = latest_probe.get((gpu.id, p["provider_id"]))
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
                        probe_method=probe["probe_method"] if probe else None,
                        last_probed_at=probe["observed_at"] if probe else None,
                        attrs_json=json.dumps(p["attrs"]) if p["attrs"] else None,
                    )
                )
                provider_rows += 1

            history_rows += _compute_price_history(
                session,
                gpu.id,
                snapshot_at,
                providers_by_id,
                parser_version=parser_filter,
            )

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


def _latest_prices(
    session: Session,
    gpu_type_id: int,
    hours: int,
    parser_version: int | None,
) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    q = session.query(
        PriceObservation.provider_id,
        PriceObservation.region,
        PriceObservation.instance_sku,
        PriceObservation.billing_kind,
        func.max(PriceObservation.observed_at).label("max_at"),
    ).filter(
        PriceObservation.gpu_type_id == gpu_type_id,
        PriceObservation.observed_at >= since,
    )
    if parser_version is not None:
        q = q.filter(PriceObservation.parser_version == parser_version)
    subq = q.group_by(
        PriceObservation.provider_id,
        PriceObservation.region,
        PriceObservation.instance_sku,
        PriceObservation.billing_kind,
    ).subquery()

    rows = (
        session.query(PriceObservation)
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
            "attrs": _parse_attrs(r.attrs_json),
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
        if status == AvailabilityStatus.UNKNOWN.value:
            continue
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
        if status == AvailabilityStatus.UNKNOWN.value:
            continue
        key = (gpu_id, provider_id, region)
        totals[key] += cnt
        if status == AvailabilityStatus.AVAILABLE.value:
            available[key] += cnt
    return {
        key: available[key] / totals[key]
        for key in totals
        if totals[key] > 0
    }


def _latest_probe_info(
    session: Session, hours: int
) -> dict[tuple[int, int], dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        session.query(AvailabilityObservation)
        .filter(AvailabilityObservation.observed_at >= since)
        .order_by(AvailabilityObservation.observed_at.desc())
        .all()
    )
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        key = (row.gpu_type_id, row.provider_id)
        if key not in out:
            out[key] = {
                "probe_method": row.probe_method,
                "observed_at": row.observed_at,
            }
    return out


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
        if status == AvailabilityStatus.UNKNOWN.value:
            continue
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
    session: Session,
    gpu_type_id: int,
    snapshot_at: datetime,
    providers_by_id: dict[int, Provider],
    parser_version: int | None,
) -> int:
    since = datetime.now(UTC) - timedelta(days=HISTORY_DAYS)
    q = session.query(PriceObservation).filter(
        PriceObservation.gpu_type_id == gpu_type_id,
        PriceObservation.observed_at >= since,
        PriceObservation.billing_kind == BillingKind.ON_DEMAND.value,
    )
    if parser_version is not None:
        q = q.filter(PriceObservation.parser_version == parser_version)
    rows = q.all()
    if not rows:
        return 0

    by_hour: dict[datetime, list[tuple[float, int, dict[str, Any]]]] = defaultdict(list)
    for row in rows:
        slug = providers_by_id[row.provider_id].slug if row.provider_id in providers_by_id else ""
        attrs = _parse_attrs(row.attrs_json)
        if not is_index_eligible(
            provider_slug=slug,
            billing_kind=row.billing_kind,
            attrs=attrs,
        ):
            continue
        bucket = _hour_bucket(row.observed_at)
        by_hour[bucket].append((row.price_per_gpu_hour_usd, row.provider_id, attrs))

    count = 0
    for bucket, entries in sorted(by_hour.items()):
        prices = sorted(e[0] for e in entries)
        providers = {e[1] for e in entries}
        session.add(
            PriceHistoryPoint(
                snapshot_at=snapshot_at,
                gpu_type_id=gpu_type_id,
                hour_bucket=bucket,
                billing_kind=BillingKind.ON_DEMAND.value,
                min_per_gpu_hour_usd=prices[0],
                median_per_gpu_hour_usd=float(statistics.median(prices)),
                max_per_gpu_hour_usd=prices[-1],
                p10_per_gpu_hour_usd=_percentile(prices, 0.10),
                p90_per_gpu_hour_usd=_percentile(prices, 0.90),
                provider_count=len(providers),
                eligible_offer_count=len(prices),
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
