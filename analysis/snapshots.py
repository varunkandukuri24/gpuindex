"""Derived price snapshot reports."""

from __future__ import annotations

import argparse
import statistics
import sys
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv
from sqlalchemy import func

from db.models import GpuType, PriceObservation, Provider
from db.session import SessionLocal, engine

load_dotenv()


def latest_prices_for_gpu(session, gpu_name: str, hours: int = 24) -> list[tuple]:
    """Return latest per-provider per-GPU-hour prices for a canonical GPU type."""
    since = datetime.now(UTC) - timedelta(hours=hours)

    gpu_type = session.query(GpuType).filter_by(name=gpu_name).one_or_none()
    if gpu_type is None:
        return []

    # Latest observation per (provider, region, instance_sku, billing_kind)
    subq = (
        session.query(
            PriceObservation.provider_id,
            PriceObservation.region,
            PriceObservation.instance_sku,
            PriceObservation.billing_kind,
            func.max(PriceObservation.observed_at).label("max_observed_at"),
        )
        .filter(
            PriceObservation.gpu_type_id == gpu_type.id,
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
            Provider.name,
            Provider.slug,
            PriceObservation.region,
            PriceObservation.billing_kind,
            PriceObservation.price_per_gpu_hour_usd,
            PriceObservation.observed_at,
        )
        .join(Provider, PriceObservation.provider_id == Provider.id)
        .join(
            subq,
            (PriceObservation.provider_id == subq.c.provider_id)
            & (PriceObservation.region == subq.c.region)
            & (PriceObservation.instance_sku == subq.c.instance_sku)
            & (PriceObservation.billing_kind == subq.c.billing_kind)
            & (PriceObservation.observed_at == subq.c.max_observed_at),
        )
        .filter(PriceObservation.gpu_type_id == gpu_type.id)
        .order_by(PriceObservation.price_per_gpu_hour_usd)
        .all()
    )
    return rows


def print_gpu_report(gpu_name: str, hours: int = 24) -> int:
    session = SessionLocal()
    try:
        rows = latest_prices_for_gpu(session, gpu_name, hours=hours)
        if not rows:
            print(f"No price observations for {gpu_name} in the last {hours}h.")
            return 1

        prices = [row.price_per_gpu_hour_usd for row in rows]
        print(f"GPU: {gpu_name}")
        print(f"Window: last {hours}h | Observations: {len(rows)}")
        print(f"Per-GPU-hour USD — min: ${min(prices):.4f}  median: ${statistics.median(prices):.4f}  max: ${max(prices):.4f}")
        print()
        print(f"{'Provider':<20} {'Region':<22} {'Billing':<12} {'$/GPU-hr':>10}")
        print("-" * 68)
        for row in rows[:50]:
            print(
                f"{row.slug:<20} {row.region:<22} {row.billing_kind:<12} "
                f"${row.price_per_gpu_hour_usd:>9.4f}"
            )
        if len(rows) > 50:
            print(f"... and {len(rows) - 50} more rows")
        return 0
    finally:
        session.close()
        engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="GPU price snapshot report")
    parser.add_argument("--gpu", required=True, help="Canonical GPU name, e.g. H100-SXM-80GB")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours")
    args = parser.parse_args(argv)
    sys.exit(print_gpu_report(args.gpu, hours=args.hours))


if __name__ == "__main__":
    main()
