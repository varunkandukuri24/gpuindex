"""RunPod GraphQL collector — GPU types and lowest prices."""

from __future__ import annotations

from datetime import UTC, datetime

from collectors.base import (
    BaseCollector,
    BillingKind,
    CollectorResult,
    ObservationSource,
    PriceObservationData,
)
from collectors.gpu_normalize import normalize_gpu
from collectors.http_util import get_client
from config import settings

RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"

GPU_TYPES_QUERY = """
query GpuTypes {
  gpuTypes {
    id
    displayName
    memoryInGb
    secureCloud
    communityCloud
    lowestPrice {
      minimumBidPrice
      uninterruptablePrice
    }
  }
}
"""


class RunPodCollector(BaseCollector):
    name = "runpod-api"
    min_interval_seconds = 3600

    def fetch(self) -> CollectorResult:
        now = datetime.now(UTC)
        result = CollectorResult()

        headers = {"Content-Type": "application/json"}
        if settings.runpod_api_key:
            headers["Authorization"] = f"Bearer {settings.runpod_api_key}"

        with get_client(timeout=30.0) as client:
            response = client.post(
                RUNPOD_GRAPHQL_URL,
                json={"query": GPU_TYPES_QUERY},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()

        if payload.get("errors"):
            raise RuntimeError(f"RunPod GraphQL errors: {payload['errors']}")

        gpu_types = (payload.get("data") or {}).get("gpuTypes") or []
        if not gpu_types:
            raise RuntimeError("RunPod: empty gpuTypes response")

        result.raw_payloads.append(self.store_json_payload(payload))

        for gpu in gpu_types:
            normalized = normalize_gpu(gpu.get("id") or gpu.get("displayName") or "")
            if normalized is None:
                continue

            memory_gb = gpu.get("memoryInGb")
            prices = gpu.get("lowestPrice") or {}
            clouds = []
            if gpu.get("secureCloud"):
                clouds.append("secure")
            if gpu.get("communityCloud"):
                clouds.append("community")
            if not clouds:
                clouds = ["unknown"]

            for cloud in clouds:
                region = f"runpod-{cloud}"
                instance_sku = f"runpod-{cloud}-{gpu.get('id', 'unknown')}"

                spot = prices.get("minimumBidPrice")
                if spot is not None and spot > 0:
                    result.price_observations.append(
                        PriceObservationData(
                            provider_slug="runpod-api",
                            gpu_type_name=normalized.canonical_name,
                            region=region,
                            instance_sku=instance_sku,
                            gpu_count=1,
                            ram_gb=float(memory_gb) if memory_gb else None,
                            price_hourly_usd=float(spot),
                            billing_kind=BillingKind.SPOT.value,
                            source=ObservationSource.API.value,
                            observed_at=now,
                        )
                    )

                on_demand = prices.get("uninterruptablePrice")
                if on_demand is not None and on_demand > 0:
                    result.price_observations.append(
                        PriceObservationData(
                            provider_slug="runpod-api",
                            gpu_type_name=normalized.canonical_name,
                            region=region,
                            instance_sku=instance_sku,
                            gpu_count=1,
                            ram_gb=float(memory_gb) if memory_gb else None,
                            price_hourly_usd=float(on_demand),
                            billing_kind=BillingKind.ON_DEMAND.value,
                            source=ObservationSource.API.value,
                            observed_at=now,
                        )
                    )

        return result
