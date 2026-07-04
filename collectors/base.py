"""Base collector abstract class with retry, timeout, and structured logging."""

from __future__ import annotations

import gzip
import json
import logging
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from collectors.gpu_normalize import NormalizedGpu, normalize_gpu
from collectors.providers import PROVIDER_REGISTRY
from config import settings
from db.models import (
    AvailabilityObservation,
    AvailabilityStatus,
    BillingKind,
    ObservationSource,
    PriceObservation,
    ProbeMethod,
    RawPayload,
)
from logging_utils import log_extra

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0


@dataclass
class PriceObservationData:
    provider_slug: str
    gpu_type_name: str
    region: str
    instance_sku: str
    gpu_count: int
    price_hourly_usd: float
    billing_kind: str = BillingKind.ON_DEMAND.value
    source: str = ObservationSource.API.value
    vcpus: int | None = None
    ram_gb: float | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def price_per_gpu_hour_usd(self) -> float:
        if self.gpu_count <= 0:
            return self.price_hourly_usd
        return self.price_hourly_usd / self.gpu_count


@dataclass
class AvailabilityObservationData:
    provider_slug: str
    gpu_type_name: str
    region: str
    instance_sku: str
    status: str
    probe_method: str
    detail: str | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


ObservationData = PriceObservationData | AvailabilityObservationData


@dataclass
class CollectorResult:
    price_observations: list[PriceObservationData] = field(default_factory=list)
    availability_observations: list[AvailabilityObservationData] = field(
        default_factory=list
    )
    raw_payloads: list[tuple[str, bytes]] = field(default_factory=list)


class BaseCollector(ABC):
    """Abstract base for all provider collectors."""

    name: str
    min_interval_seconds: int = 3600

    def __init__(self) -> None:
        self._provider_cache: dict[str, int] = {}
        self._gpu_type_cache: dict[str, int] = {}

    @abstractmethod
    def fetch(self) -> CollectorResult:
        """Fetch observations from the provider. Must not raise — errors as rows."""

    def run(self, session: Session) -> tuple[int, int]:
        """Execute fetch with retries, timeout, and persistence."""
        started_at = datetime.now(UTC)
        log_extra(
            logger,
            logging.INFO,
            "collector_run_started",
            collector=self.name,
        )

        result: CollectorResult | None = None
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = self._fetch_with_timeout()
                break
            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    backoff = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    log_extra(
                        logger,
                        logging.WARNING,
                        "collector_fetch_retry",
                        collector=self.name,
                        attempt=attempt,
                        backoff_seconds=backoff,
                        error=str(exc),
                    )
                    time.sleep(backoff)

        if result is None:
            log_extra(
                logger,
                logging.ERROR,
                "collector_fetch_failed",
                collector=self.name,
                error=str(last_error),
            )
            self._write_error_availability(session, str(last_error))
            session.flush()
            return 0, 1

        price_count = self._persist_result(session, result)

        log_extra(
            logger,
            logging.INFO,
            "collector_run_finished",
            collector=self.name,
            price_rows=price_count,
            availability_rows=len(result.availability_observations),
            duration_seconds=(datetime.now(UTC) - started_at).total_seconds(),
        )
        return price_count, len(result.availability_observations)

    def _fetch_with_timeout(self) -> CollectorResult:
        timeout = settings.collector_timeout_seconds
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.fetch)
            try:
                return future.result(timeout=timeout)
            except FuturesTimeoutError as exc:
                raise TimeoutError(
                    f"Collector {self.name} timed out after {timeout}s"
                ) from exc

    def _persist_result(self, session: Session, result: CollectorResult) -> int:
        for content_type, payload in result.raw_payloads:
            session.add(
                RawPayload(
                    collector_name=self.name,
                    observed_at=datetime.now(UTC),
                    payload_gzip=gzip.compress(payload),
                    content_type=content_type,
                )
            )

        price_count = 0
        for obs in result.price_observations:
            provider_id = self._resolve_provider(session, obs.provider_slug)
            gpu_type_id = self._resolve_gpu_type(session, obs.gpu_type_name)
            session.add(
                PriceObservation(
                    provider_id=provider_id,
                    gpu_type_id=gpu_type_id,
                    region=obs.region,
                    instance_sku=obs.instance_sku,
                    gpu_count=obs.gpu_count,
                    vcpus=obs.vcpus,
                    ram_gb=obs.ram_gb,
                    price_hourly_usd=obs.price_hourly_usd,
                    price_per_gpu_hour_usd=obs.price_per_gpu_hour_usd,
                    billing_kind=obs.billing_kind,
                    observed_at=obs.observed_at,
                    source=obs.source,
                )
            )
            price_count += 1

        for obs in result.availability_observations:
            provider_id = self._resolve_provider(session, obs.provider_slug)
            gpu_type_id = self._resolve_gpu_type(session, obs.gpu_type_name)
            session.add(
                AvailabilityObservation(
                    provider_id=provider_id,
                    gpu_type_id=gpu_type_id,
                    region=obs.region,
                    instance_sku=obs.instance_sku,
                    status=obs.status,
                    detail=obs.detail,
                    probe_method=obs.probe_method,
                    observed_at=obs.observed_at,
                )
            )

        session.flush()
        return price_count

    def _write_error_availability(self, session: Session, error: str) -> None:
        provider_id = self._resolve_provider(session, self.name)
        gpu_type_id = self._resolve_gpu_type(session, "UNKNOWN")
        session.add(
            AvailabilityObservation(
                provider_id=provider_id,
                gpu_type_id=gpu_type_id,
                region="global",
                instance_sku="collector-error",
                status=AvailabilityStatus.ERROR.value,
                detail=error[:2000],
                probe_method=ProbeMethod.CAPACITY_API.value,
                observed_at=datetime.now(UTC),
            )
        )

    def _resolve_provider(self, session: Session, slug: str) -> int:
        if slug in self._provider_cache:
            return self._provider_cache[slug]

        from db.models import ApiType, Provider, ProviderKind

        provider = session.query(Provider).filter_by(slug=slug).one_or_none()
        if provider is None:
            display_name, kind, api_type = PROVIDER_REGISTRY.get(
                slug,
                (slug.replace("-", " ").title(), ProviderKind.NEOCLOUD.value, ApiType.REST.value),
            )
            provider = Provider(
                name=display_name,
                slug=slug,
                kind=kind,
                api_type=api_type,
            )
            session.add(provider)
            session.flush()
        self._provider_cache[slug] = provider.id
        return provider.id

    def _resolve_gpu_type(self, session: Session, name: str) -> int:
        if name in self._gpu_type_cache:
            return self._gpu_type_cache[name]

        from db.models import GpuType

        gpu_type = session.query(GpuType).filter_by(name=name).one_or_none()
        if gpu_type is None:
            gpu_type = GpuType(name=name)
            session.add(gpu_type)
            session.flush()
        self._gpu_type_cache[name] = gpu_type.id
        return gpu_type.id

    def normalize_gpu_name(
        self,
        raw_name: str,
        *,
        vram_mb: int | None = None,
        instance_sku: str | None = None,
    ) -> NormalizedGpu | None:
        return normalize_gpu(raw_name, vram_mb=vram_mb, instance_sku=instance_sku)

    def _resolve_gpu_type_normalized(
        self,
        session: Session,
        raw_name: str,
        *,
        vram_mb: int | None = None,
        instance_sku: str | None = None,
    ) -> tuple[int, str] | None:
        normalized = self.normalize_gpu_name(
            raw_name, vram_mb=vram_mb, instance_sku=instance_sku
        )
        if normalized is None:
            return None

        from db.models import GpuType

        gpu_type = session.query(GpuType).filter_by(name=normalized.canonical_name).one_or_none()
        if gpu_type is None:
            gpu_type = GpuType(
                name=normalized.canonical_name,
                vram_gb=normalized.vram_gb,
                architecture=normalized.architecture,
            )
            session.add(gpu_type)
            session.flush()
        elif normalized.vram_gb and gpu_type.vram_gb is None:
            gpu_type.vram_gb = normalized.vram_gb
            gpu_type.architecture = normalized.architecture

        self._gpu_type_cache[normalized.canonical_name] = gpu_type.id
        return gpu_type.id, normalized.canonical_name

    @staticmethod
    def store_json_payload(data: Any) -> tuple[str, bytes]:
        return ("application/json", json.dumps(data, default=str).encode("utf-8"))
