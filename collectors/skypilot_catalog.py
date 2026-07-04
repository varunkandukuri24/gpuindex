"""SkyPilot catalog CSV collector — multi-cloud list prices."""

from __future__ import annotations

import csv
import io
import logging
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
from collectors.providers import SKYPILOT_SKIP_PROVIDERS
from logging_utils import log_extra

logger = logging.getLogger(__name__)

CATALOG_BASE = (
    "https://raw.githubusercontent.com/skypilot-org/skypilot-catalog/master/catalogs/v7"
)
GITHUB_API = (
    "https://api.github.com/repos/skypilot-org/skypilot-catalog/contents/catalogs/v7"
)


class SkyPilotCatalogCollector(BaseCollector):
    name = "skypilot-catalog"
    min_interval_seconds = 3600

    def fetch(self) -> CollectorResult:
        now = datetime.now(UTC)
        result = CollectorResult()
        raw_by_provider: dict[str, str] = {}

        with get_client(timeout=60.0) as client:
            providers = self._list_providers(client)
            for provider in providers:
                try:
                    url = f"{CATALOG_BASE}/{provider}/vms.csv"
                    response = client.get(url)
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    raw_by_provider[provider] = response.text
                    self._parse_provider_csv(provider, response.text, now, result)
                except Exception as exc:
                    log_extra(
                        logger,
                        logging.WARNING,
                        "skypilot_provider_fetch_failed",
                        provider=provider,
                        error=str(exc),
                    )

        if raw_by_provider:
            # Store a compact summary rather than every CSV verbatim
            summary = {
                provider: {"lines": text.count("\n"), "bytes": len(text)}
                for provider, text in raw_by_provider.items()
            }
            result.raw_payloads.append(self.store_json_payload(summary))
        elif not result.price_observations:
            raise RuntimeError("SkyPilot catalog: no provider CSVs fetched")

        return result

    def _list_providers(self, client) -> list[str]:
        response = client.get(GITHUB_API)
        response.raise_for_status()
        entries = response.json()
        providers = []
        for entry in entries:
            if entry.get("type") != "dir":
                continue
            name = entry["name"]
            if name in SKYPILOT_SKIP_PROVIDERS:
                continue
            providers.append(name)
        return sorted(providers)

    def _parse_provider_csv(
        self,
        provider: str,
        csv_text: str,
        observed_at: datetime,
        result: CollectorResult,
    ) -> None:
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            accelerator = (row.get("AcceleratorName") or "").strip()
            if not accelerator:
                continue

            try:
                gpu_count = int(float(row.get("AcceleratorCount") or 1))
            except ValueError:
                continue
            if gpu_count <= 0:
                continue

            normalized = normalize_gpu(
                accelerator,
                instance_sku=row.get("InstanceType") or "",
            )
            if normalized is None:
                continue

            region = (row.get("Region") or "global").strip()
            instance_sku = (row.get("InstanceType") or "unknown").strip()
            vcpus = _parse_int(row.get("vCPUs"))
            ram_gb = _parse_float(row.get("MemoryGiB"))

            on_demand = _parse_float(row.get("Price"))
            if on_demand is not None and on_demand > 0:
                result.price_observations.append(
                    PriceObservationData(
                        provider_slug=provider,
                        gpu_type_name=normalized.canonical_name,
                        region=region,
                        instance_sku=instance_sku,
                        gpu_count=gpu_count,
                        vcpus=vcpus,
                        ram_gb=ram_gb,
                        price_hourly_usd=on_demand,
                        billing_kind=BillingKind.ON_DEMAND.value,
                        source=ObservationSource.CATALOG.value,
                        observed_at=observed_at,
                    )
                )

            spot = _parse_float(row.get("SpotPrice"))
            if spot is not None and spot > 0 and spot != on_demand:
                result.price_observations.append(
                    PriceObservationData(
                        provider_slug=provider,
                        gpu_type_name=normalized.canonical_name,
                        region=region,
                        instance_sku=instance_sku,
                        gpu_count=gpu_count,
                        vcpus=vcpus,
                        ram_gb=ram_gb,
                        price_hourly_usd=spot,
                        billing_kind=BillingKind.SPOT.value,
                        source=ObservationSource.CATALOG.value,
                        observed_at=observed_at,
                    )
                )


def _parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None
