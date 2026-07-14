"""Shared collector/DB status payload for CLI and /status page."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from build_info import GIT_SHA
from db.models import (
    AvailabilityObservation,
    CollectorRun,
    PriceObservation,
    RollupRun,
    SchedulerHeartbeat,
)


def format_time(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def db_size_bytes() -> int | None:
    url = settings.database_url
    if url.startswith("sqlite:////"):
        path = url.removeprefix("sqlite:///")
    elif url.startswith("sqlite:///"):
        path = url.removeprefix("sqlite:///")
    else:
        return None
    if os.path.isfile(path):
        return os.path.getsize(path)
    return 0


def collect_status(session: Session) -> dict[str, Any]:
    last_heartbeat = (
        session.query(SchedulerHeartbeat)
        .order_by(SchedulerHeartbeat.observed_at.desc())
        .first()
    )
    price_count = session.query(func.count(PriceObservation.id)).scalar() or 0
    avail_count = session.query(func.count(AvailabilityObservation.id)).scalar() or 0
    latest_rollup = (
        session.query(RollupRun)
        .filter(RollupRun.status == "success")
        .order_by(RollupRun.snapshot_at.desc())
        .first()
    )

    collectors = (
        session.query(CollectorRun.collector_name)
        .distinct()
        .order_by(CollectorRun.collector_name)
        .all()
    )
    collector_rows = []
    for (name,) in collectors:
        run = (
            session.query(CollectorRun)
            .filter_by(collector_name=name)
            .order_by(CollectorRun.started_at.desc())
            .first()
        )
        if run:
            collector_rows.append(
                {
                    "name": name,
                    "status": run.status,
                    "started_at": run.started_at,
                    "started_at_fmt": format_time(run.started_at),
                    "price_rows_written": run.price_rows_written,
                    "availability_rows_written": run.availability_rows_written,
                    "error_message": run.error_message,
                }
            )

    return {
        "database_url": settings.database_url,
        "db_size_bytes": db_size_bytes(),
        "code_version": GIT_SHA,
        "last_heartbeat": last_heartbeat.observed_at if last_heartbeat else None,
        "last_heartbeat_fmt": format_time(
            last_heartbeat.observed_at if last_heartbeat else None
        ),
        "price_observations": price_count,
        "availability_observations": avail_count,
        "collectors": collector_rows,
        "latest_rollup_code_version": (
            latest_rollup.code_version if latest_rollup else None
        ),
        "latest_rollup_at_fmt": format_time(
            latest_rollup.snapshot_at if latest_rollup else None
        ),
        "code_mismatch": bool(
            latest_rollup
            and latest_rollup.code_version
            and latest_rollup.code_version != GIT_SHA
        ),
    }
