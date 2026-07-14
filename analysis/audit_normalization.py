"""One-off audit: multi-GPU price_per_gpu_hour_usd vs price_hourly / gpu_count."""

from __future__ import annotations

import json
import sys
from collections import defaultdict

from dotenv import load_dotenv
from sqlalchemy import desc

from collectors.parser_version import CURRENT_PARSER_VERSION
from db.models import PriceObservation, Provider, RawPayload
from db.session import SessionLocal, engine

load_dotenv()

SAMPLE_PER_PROVIDER = 20
TOLERANCE = 1e-6


def main() -> int:
    session = SessionLocal()
    mismatches = 0
    try:
        providers = session.query(Provider).order_by(Provider.slug).all()
        print(f"Current parser_version: {CURRENT_PARSER_VERSION}")
        print("=" * 72)

        for provider in providers:
            rows = (
                session.query(PriceObservation)
                .filter(
                    PriceObservation.provider_id == provider.id,
                    PriceObservation.gpu_count > 1,
                )
                .order_by(desc(PriceObservation.observed_at))
                .limit(SAMPLE_PER_PROVIDER)
                .all()
            )
            print(f"\nProvider {provider.slug!r}: {len(rows)} multi-GPU samples")
            if not rows:
                continue

            for row in rows:
                recomputed = (
                    row.price_hourly_usd / row.gpu_count
                    if row.gpu_count > 0
                    else row.price_hourly_usd
                )
                ok = abs(recomputed - row.price_per_gpu_hour_usd) <= TOLERANCE
                flag = "OK" if ok else "MISMATCH"
                if not ok:
                    mismatches += 1
                print(
                    f"  [{flag}] id={row.id} sku={row.instance_sku[:40]!r} "
                    f"gpus={row.gpu_count} hourly={row.price_hourly_usd:.4f} "
                    f"stored_per={row.price_per_gpu_hour_usd:.4f} "
                    f"recomputed={recomputed:.4f} "
                    f"billing={row.billing_kind} "
                    f"parser_v={getattr(row, 'parser_version', '?')}"
                )

        print("\n" + "=" * 72)
        print("Vast raw payload sample (latest):")
        vast_raw = (
            session.query(RawPayload)
            .filter(RawPayload.collector_name == "vast")
            .order_by(desc(RawPayload.observed_at))
            .first()
        )
        if vast_raw is None:
            print("  (no vast raw payloads)")
        else:
            import gzip

            try:
                payload = json.loads(gzip.decompress(vast_raw.payload_gzip))
                sample = payload.get("sample") or []
                for offer in sample[:5]:
                    print(
                        "  offer:",
                        {
                            "id": offer.get("id"),
                            "num_gpus": offer.get("num_gpus"),
                            "dph_total": offer.get("dph_total"),
                            "dph_base": offer.get("dph_base"),
                            "is_bid": offer.get("is_bid"),
                            "reliability": offer.get("reliability"),
                            "reliability2": offer.get("reliability2"),
                            "verified": offer.get("verified"),
                        },
                    )
            except Exception as exc:
                print(f"  failed to decode raw payload: {exc}")

        print("\n" + "=" * 72)
        print(f"Mismatches: {mismatches}")
        return 1 if mismatches else 0
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
