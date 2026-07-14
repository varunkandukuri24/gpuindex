"""Vast.ai marketplace collector — prices and availability from live listings."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from collectors.base import (
    AvailabilityObservationData,
    AvailabilityStatus,
    BaseCollector,
    BillingKind,
    CollectorResult,
    ObservationSource,
    PriceObservationData,
    ProbeMethod,
)
from collectors.gpu_normalize import normalize_gpu
from collectors.http_util import get_client
from collectors.parser_version import CURRENT_PARSER_VERSION
from logging_utils import log_extra

logger = logging.getLogger(__name__)

VAST_BUNDLES_URL = "https://console.vast.ai/api/v0/bundles/"
PAGE_SIZE = 512

# Fetch both fixed-price and interruptible inventory with correct billing_kind.
# Previously we only queried type=bid, which let interruptible prices set headlines.
VAST_QUERY_TYPES: tuple[tuple[str, str], ...] = (
    ("on_demand", BillingKind.ON_DEMAND.value),
    ("bid", BillingKind.SPOT.value),
)


class VastCollector(BaseCollector):
    name = "vast"
    min_interval_seconds = 3600

    def fetch(self) -> CollectorResult:
        now = datetime.now(UTC)
        result = CollectorResult()
        all_offers: list[dict] = []
        seen_ids: set[int | str] = set()

        with get_client(timeout=60.0) as client:
            for query_type, default_billing in VAST_QUERY_TYPES:
                response = client.post(
                    VAST_BUNDLES_URL,
                    json={"limit": PAGE_SIZE, "type": query_type},
                )
                response.raise_for_status()
                payload = response.json()
                offers = payload.get("offers") or []
                for offer in offers:
                    oid = offer.get("id")
                    if oid is not None and oid in seen_ids:
                        continue
                    if oid is not None:
                        seen_ids.add(oid)
                    # Annotate requested query type for billing classification.
                    offer = {**offer, "_query_type": query_type, "_default_billing": default_billing}
                    all_offers.append(offer)

        all_offers = [
            o for o in all_offers if o.get("rentable") and not o.get("rented")
        ]

        if not all_offers:
            raise RuntimeError("Vast.ai: no rentable offers returned")

        result.raw_payloads.append(
            self.store_json_payload(
                {
                    "offer_count": len(all_offers),
                    "sample": all_offers[:3],
                    "query_types": [t for t, _ in VAST_QUERY_TYPES],
                }
            )
        )

        for offer in all_offers:
            gpu_name = offer.get("gpu_name") or ""
            gpu_ram_mb = offer.get("gpu_ram")
            normalized = normalize_gpu(gpu_name, vram_mb=gpu_ram_mb)
            if normalized is None:
                continue

            num_gpus = int(offer.get("num_gpus") or 1)
            # dph_total is machine $/hr; divide by num_gpus downstream via gpu_count.
            dph_total = float(offer.get("dph_total") or 0)
            if dph_total <= 0:
                continue

            region = (offer.get("geolocation") or "global").strip()
            instance_sku = f"vast-{offer.get('id', 'unknown')}"
            rentable = bool(offer.get("rentable")) and not bool(offer.get("rented"))

            billing = _classify_billing(offer)
            attrs = {
                "reliability": offer.get("reliability2", offer.get("reliability")),
                "reliability2": offer.get("reliability2"),
                "verified": bool(
                    offer.get("verified")
                    or offer.get("host_verified")
                    or offer.get("is_verified")
                ),
                "vast_offer_id": offer.get("id"),
                "dph_base": offer.get("dph_base"),
                "query_type": offer.get("_query_type"),
                "is_bid": bool(offer.get("is_bid")),
            }

            result.price_observations.append(
                PriceObservationData(
                    provider_slug="vast",
                    gpu_type_name=normalized.canonical_name,
                    region=region,
                    instance_sku=instance_sku,
                    gpu_count=num_gpus,
                    vcpus=int(offer.get("cpu_cores") or 0) or None,
                    ram_gb=_mb_to_gb(offer.get("cpu_ram")),
                    price_hourly_usd=dph_total,
                    billing_kind=billing,
                    source=ObservationSource.API.value,
                    observed_at=now,
                    attrs=attrs,
                    parser_version=CURRENT_PARSER_VERSION,
                )
            )

            status = (
                AvailabilityStatus.AVAILABLE.value
                if rentable
                else AvailabilityStatus.UNAVAILABLE.value
            )
            result.availability_observations.append(
                AvailabilityObservationData(
                    provider_slug="vast",
                    gpu_type_name=normalized.canonical_name,
                    region=region,
                    instance_sku=instance_sku,
                    status=status,
                    probe_method=ProbeMethod.MARKETPLACE_LISTING.value,
                    detail=(
                        f"reliability={attrs.get('reliability')} "
                        f"verified={attrs.get('verified')} billing={billing}"
                    ),
                    observed_at=now,
                )
            )

        log_extra(
            logger,
            logging.INFO,
            "vast_offers_parsed",
            offers=len(all_offers),
            prices=len(result.price_observations),
        )
        return result


def _classify_billing(offer: dict) -> str:
    """Interruptible/bid offers are spot; fixed-price rentals are on_demand."""
    if offer.get("is_bid") or offer.get("_query_type") == "bid":
        return BillingKind.SPOT.value
    return offer.get("_default_billing") or BillingKind.ON_DEMAND.value


def _mb_to_gb(value) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value) / 1024, 1)
    except (TypeError, ValueError):
        return None
