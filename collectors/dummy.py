"""Dummy collector for Phase 0 — writes synthetic price observations."""

from datetime import UTC, datetime
import random

from collectors.base import (
    BaseCollector,
    CollectorResult,
    PriceObservationData,
)
from db.models import BillingKind, ObservationSource


class DummyCollector(BaseCollector):
    """Synthetic collector to validate scheduler and persistence."""

    name = "dummy"

    def fetch(self) -> CollectorResult:
        now = datetime.now(UTC)
        base_price = random.uniform(1.5, 4.0)

        return CollectorResult(
            price_observations=[
                PriceObservationData(
                    provider_slug="dummy-provider",
                    gpu_type_name="RTX-4090",
                    region="global",
                    instance_sku="dummy-rtx4090-1x",
                    gpu_count=1,
                    price_hourly_usd=round(base_price, 4),
                    billing_kind=BillingKind.ON_DEMAND.value,
                    source=ObservationSource.API.value,
                    observed_at=now,
                ),
                PriceObservationData(
                    provider_slug="dummy-provider",
                    gpu_type_name="A100-PCIE-40GB",
                    region="global",
                    instance_sku="dummy-a100-1x",
                    gpu_count=1,
                    price_hourly_usd=round(base_price * 3.5, 4),
                    billing_kind=BillingKind.ON_DEMAND.value,
                    source=ObservationSource.API.value,
                    observed_at=now,
                ),
            ],
            raw_payloads=[
                self.store_json_payload(
                    {
                        "dummy": True,
                        "observed_at": now.isoformat(),
                        "base_price": base_price,
                    }
                )
            ],
        )
