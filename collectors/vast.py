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
from logging_utils import log_extra

logger = logging.getLogger(__name__)

VAST_BUNDLES_URL = "https://console.vast.ai/api/v0/bundles/"
PAGE_SIZE = 512


class VastCollector(BaseCollector):
    name = "vast"
    min_interval_seconds = 3600

    def fetch(self) -> CollectorResult:
        now = datetime.now(UTC)
        result = CollectorResult()

        with get_client(timeout=60.0) as client:
            response = client.post(
                VAST_BUNDLES_URL,
                json={"limit": PAGE_SIZE, "type": "bid"},
            )
            response.raise_for_status()
            payload = response.json()
            all_offers = payload.get("offers") or []

        # Filter to rentable, unrented listings (marketplace availability signal)
        all_offers = [
            o for o in all_offers if o.get("rentable") and not o.get("rented")
        ]

        if not all_offers:
            raise RuntimeError("Vast.ai: no rentable offers returned")

        result.raw_payloads.append(
            self.store_json_payload({"offer_count": len(all_offers), "sample": all_offers[:3]})
        )

        for offer in all_offers:
            gpu_name = offer.get("gpu_name") or ""
            gpu_ram_mb = offer.get("gpu_ram")
            normalized = normalize_gpu(gpu_name, vram_mb=gpu_ram_mb)
            if normalized is None:
                continue

            num_gpus = int(offer.get("num_gpus") or 1)
            dph_total = float(offer.get("dph_total") or 0)
            if dph_total <= 0:
                continue

            region = (offer.get("geolocation") or "global").strip()
            instance_sku = f"vast-{offer.get('id', 'unknown')}"
            rentable = bool(offer.get("rentable")) and not bool(offer.get("rented"))

            billing = BillingKind.SPOT.value if offer.get("is_bid") else BillingKind.ON_DEMAND.value

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
                )
            )

            status = AvailabilityStatus.AVAILABLE.value if rentable else AvailabilityStatus.UNAVAILABLE.value
            result.availability_observations.append(
                AvailabilityObservationData(
                    provider_slug="vast",
                    gpu_type_name=normalized.canonical_name,
                    region=region,
                    instance_sku=instance_sku,
                    status=status,
                    probe_method=ProbeMethod.MARKETPLACE_LISTING.value,
                    detail=f"reliability={offer.get('reliability')}",
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


def _mb_to_gb(value) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value) / 1024, 1)
    except (TypeError, ValueError):
        return None
