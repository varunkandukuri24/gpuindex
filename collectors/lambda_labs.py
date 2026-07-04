"""Lambda Cloud REST collector — pricing and capacity signals."""

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
from config import settings
from logging_utils import log_extra

logger = logging.getLogger(__name__)

LAMBDA_API_BASE = "https://cloud.lambda.ai/api/v1"


class LambdaLabsCollector(BaseCollector):
    name = "lambda-api"
    min_interval_seconds = 3600

    def fetch(self) -> CollectorResult:
        now = datetime.now(UTC)
        result = CollectorResult()

        if not settings.lambda_api_key:
            log_extra(
                logger,
                logging.INFO,
                "lambda_api_degraded",
                detail="No LAMBDA_API_KEY; skipping Lambda collector",
            )
            return result

        with get_client(timeout=30.0) as client:
            response = client.get(
                f"{LAMBDA_API_BASE}/instance-types",
                headers={
                    "Authorization": f"Bearer {settings.lambda_api_key}",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            payload = response.json()

        result.raw_payloads.append(self.store_json_payload(payload))

        data = payload.get("data") if isinstance(payload, dict) else payload
        if not data:
            raise RuntimeError("Lambda: empty instance-types response")

        for type_key, entry in data.items():
            instance_type = entry.get("instance_type") or {}
            description = instance_type.get("description") or type_key
            name = instance_type.get("name") or type_key
            specs = instance_type.get("specs") or {}

            normalized = normalize_gpu(description, instance_sku=name)
            if normalized is None:
                continue

            price_cents = instance_type.get("price_cents_per_hour")
            if price_cents is None:
                continue
            price_hourly = float(price_cents) / 100.0

            regions = entry.get("regions_with_capacity_available") or []
            if not regions:
                # Still record list price with no capacity signal
                result.price_observations.append(
                    PriceObservationData(
                        provider_slug="lambda-api",
                        gpu_type_name=normalized.canonical_name,
                        region="global",
                        instance_sku=name,
                        gpu_count=_gpu_count_from_name(name),
                        vcpus=specs.get("vcpus"),
                        ram_gb=specs.get("memory_gib"),
                        price_hourly_usd=price_hourly,
                        billing_kind=BillingKind.ON_DEMAND.value,
                        source=ObservationSource.API.value,
                        observed_at=now,
                    )
                )
                result.availability_observations.append(
                    AvailabilityObservationData(
                        provider_slug="lambda-api",
                        gpu_type_name=normalized.canonical_name,
                        region="global",
                        instance_sku=name,
                        status=AvailabilityStatus.UNAVAILABLE.value,
                        probe_method=ProbeMethod.CAPACITY_API.value,
                        detail="no regions_with_capacity_available",
                        observed_at=now,
                    )
                )
                continue

            for region_entry in regions:
                region_name = region_entry.get("name") or "unknown"
                gpu_count = _gpu_count_from_name(name)

                result.price_observations.append(
                    PriceObservationData(
                        provider_slug="lambda-api",
                        gpu_type_name=normalized.canonical_name,
                        region=region_name,
                        instance_sku=name,
                        gpu_count=gpu_count,
                        vcpus=specs.get("vcpus"),
                        ram_gb=specs.get("memory_gib"),
                        price_hourly_usd=price_hourly,
                        billing_kind=BillingKind.ON_DEMAND.value,
                        source=ObservationSource.API.value,
                        observed_at=now,
                    )
                )
                result.availability_observations.append(
                    AvailabilityObservationData(
                        provider_slug="lambda-api",
                        gpu_type_name=normalized.canonical_name,
                        region=region_name,
                        instance_sku=name,
                        status=AvailabilityStatus.AVAILABLE.value,
                        probe_method=ProbeMethod.CAPACITY_API.value,
                        detail=region_entry.get("description"),
                        observed_at=now,
                    )
                )

        return result


def _gpu_count_from_name(name: str) -> int:
    # e.g. gpu_8x_h100_sxm -> 8
    parts = name.lower().split("_")
    for part in parts:
        if part.endswith("x") and part[:-1].isdigit():
            return int(part[:-1])
    return 1
