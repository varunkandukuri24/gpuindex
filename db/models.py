"""SQLAlchemy ORM models for GPU market intelligence."""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ProviderKind(str, Enum):
    HYPERSCALER = "hyperscaler"
    NEOCLOUD = "neocloud"
    MARKETPLACE = "marketplace"


class ApiType(str, Enum):
    REST = "rest"
    GRAPHQL = "graphql"
    CATALOG_SCRAPE = "catalog_scrape"


class BillingKind(str, Enum):
    ON_DEMAND = "on_demand"
    SPOT = "spot"
    RESERVED_1YR = "reserved_1yr"


class ObservationSource(str, Enum):
    API = "api"
    CATALOG = "catalog"
    SCRAPE = "scrape"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"
    UNKNOWN = "unknown"


class ProbeMethod(str, Enum):
    MARKETPLACE_LISTING = "marketplace_listing"
    CAPACITY_API = "capacity_api"
    DRY_RUN = "dry_run"
    LAUNCH_ATTEMPT = "launch_attempt"


class CanaryEndReason(str, Enum):
    COMPLETED = "completed"
    PREEMPTED = "preempted"
    PROVIDER_ERROR = "provider_error"


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    api_type: Mapped[str] = mapped_column(String(32), nullable=False)

    price_observations: Mapped[list["PriceObservation"]] = relationship(
        back_populates="provider"
    )
    availability_observations: Mapped[list["AvailabilityObservation"]] = relationship(
        back_populates="provider"
    )


class GpuType(Base):
    __tablename__ = "gpu_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    vram_gb: Mapped[int | None] = mapped_column(Integer)
    architecture: Mapped[str | None] = mapped_column(String(32))

    price_observations: Mapped[list["PriceObservation"]] = relationship(
        back_populates="gpu_type"
    )
    availability_observations: Mapped[list["AvailabilityObservation"]] = relationship(
        back_populates="gpu_type"
    )


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        Index(
            "ix_price_obs_provider_gpu_region_time",
            "provider_id",
            "gpu_type_id",
            "region",
            "observed_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False)
    gpu_type_id: Mapped[int] = mapped_column(ForeignKey("gpu_types.id"), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False, default="global")
    instance_sku: Mapped[str] = mapped_column(String(256), nullable=False)
    gpu_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    vcpus: Mapped[int | None] = mapped_column(Integer)
    ram_gb: Mapped[float | None] = mapped_column(Float)
    price_hourly_usd: Mapped[float] = mapped_column(Float, nullable=False)
    price_per_gpu_hour_usd: Mapped[float] = mapped_column(Float, nullable=False)
    billing_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    provider: Mapped["Provider"] = relationship(back_populates="price_observations")
    gpu_type: Mapped["GpuType"] = relationship(back_populates="price_observations")


class AvailabilityObservation(Base):
    __tablename__ = "availability_observations"
    __table_args__ = (
        Index(
            "ix_avail_obs_provider_gpu_region_time",
            "provider_id",
            "gpu_type_id",
            "region",
            "observed_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False)
    gpu_type_id: Mapped[int] = mapped_column(ForeignKey("gpu_types.id"), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False, default="global")
    instance_sku: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    probe_method: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    provider: Mapped["Provider"] = relationship(
        back_populates="availability_observations"
    )
    gpu_type: Mapped["GpuType"] = relationship(
        back_populates="availability_observations"
    )


class CanaryRun(Base):
    """Tier 3 canary runs — schema defined now, implementation deferred to Phase 4."""

    __tablename__ = "canary_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False)
    gpu_type_id: Mapped[int] = mapped_column(ForeignKey("gpu_types.id"), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(32))
    provision_latency_s: Mapped[float | None] = mapped_column(Float)
    advertised_price: Mapped[float | None] = mapped_column(Float)
    billed_price: Mapped[float | None] = mapped_column(Float)


class RawPayload(Base):
    """Gzipped raw API responses for later reprocessing."""

    __tablename__ = "raw_payloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collector_name: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    payload_gzip: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(64))


class CollectorRun(Base):
    """Heartbeat and status log for each collector poll cycle."""

    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collector_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    price_rows_written: Mapped[int] = mapped_column(Integer, default=0)
    availability_rows_written: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class SchedulerHeartbeat(Base):
    """Periodic heartbeat from the long-running scheduler process."""

    __tablename__ = "scheduler_heartbeats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    process_id: Mapped[int] = mapped_column(Integer, nullable=False)
    message: Mapped[str] = mapped_column(String(256), nullable=False, default="alive")


class RollupRun(Base):
    """Audit log for hourly snapshot rollup jobs."""

    __tablename__ = "rollup_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, unique=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    gpu_index_rows: Mapped[int] = mapped_column(Integer, default=0)
    price_history_rows: Mapped[int] = mapped_column(Integer, default=0)
    provider_snapshot_rows: Mapped[int] = mapped_column(Integer, default=0)
    availability_daily_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class GpuIndexSnapshot(Base):
    """Index page rollup — one row per GPU type per snapshot."""

    __tablename__ = "gpu_index_snapshots"
    __table_args__ = (
        Index("ix_gpu_index_snapshots_at_gpu", "snapshot_at", "gpu_type_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    gpu_type_id: Mapped[int] = mapped_column(ForeignKey("gpu_types.id"), nullable=False)
    cheapest_listed_per_gpu_hour_usd: Mapped[float | None] = mapped_column(Float)
    cheapest_available_per_gpu_hour_usd: Mapped[float | None] = mapped_column(Float)
    provider_count: Mapped[int] = mapped_column(Integer, default=0)
    availability_rate_24h: Mapped[float | None] = mapped_column(Float)
    availability_indicator: Mapped[str] = mapped_column(String(16), default="unknown")


class PriceHistoryPoint(Base):
    """Hourly price rollup for charts."""

    __tablename__ = "price_history_points"
    __table_args__ = (
        Index(
            "ix_price_history_gpu_hour",
            "gpu_type_id",
            "hour_bucket",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    gpu_type_id: Mapped[int] = mapped_column(ForeignKey("gpu_types.id"), nullable=False)
    hour_bucket: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    min_per_gpu_hour_usd: Mapped[float] = mapped_column(Float, nullable=False)
    median_per_gpu_hour_usd: Mapped[float] = mapped_column(Float, nullable=False)
    max_per_gpu_hour_usd: Mapped[float] = mapped_column(Float, nullable=False)
    provider_count: Mapped[int] = mapped_column(Integer, default=0)


class ProviderGpuSnapshot(Base):
    """Provider comparison rows for GPU detail page."""

    __tablename__ = "provider_gpu_snapshots"
    __table_args__ = (
        Index(
            "ix_provider_gpu_snap_at_gpu",
            "snapshot_at",
            "gpu_type_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    gpu_type_id: Mapped[int] = mapped_column(ForeignKey("gpu_types.id"), nullable=False)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    billing_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    price_per_gpu_hour_usd: Mapped[float] = mapped_column(Float, nullable=False)
    availability_rate_24h: Mapped[float | None] = mapped_column(Float)
    availability_indicator: Mapped[str] = mapped_column(String(16), default="unknown")


class AvailabilityDailyRollup(Base):
    """Availability heatmap — provider × day."""

    __tablename__ = "availability_daily_rollups"
    __table_args__ = (
        Index(
            "ix_avail_daily_gpu_provider_day",
            "gpu_type_id",
            "provider_id",
            "day",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    gpu_type_id: Mapped[int] = mapped_column(ForeignKey("gpu_types.id"), nullable=False)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False)
    day: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    availability_rate: Mapped[float | None] = mapped_column(Float)
    poll_count: Mapped[int] = mapped_column(Integer, default=0)
