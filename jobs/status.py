"""CLI status command — last poll, row counts, DB size."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

from dotenv import load_dotenv
from sqlalchemy import func

from config import settings
from db.models import (
    AvailabilityObservation,
    CollectorRun,
    PriceObservation,
    SchedulerHeartbeat,
)
from db.session import SessionLocal, engine

load_dotenv()


def _format_time(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _db_size_bytes() -> int | None:
    if not settings.database_url.startswith("sqlite:///"):
        return None
    path = settings.database_url.removeprefix("sqlite:///")
    if os.path.isfile(path):
        return os.path.getsize(path)
    return 0


def main() -> None:
    session = SessionLocal()
    try:
        print("GPU Index — Status")
        print("=" * 40)
        print(f"Database: {settings.database_url}")

        db_size = _db_size_bytes()
        if db_size is not None:
            print(f"DB size: {db_size:,} bytes")

        last_heartbeat = (
            session.query(SchedulerHeartbeat)
            .order_by(SchedulerHeartbeat.observed_at.desc())
            .first()
        )
        print(f"Last scheduler heartbeat: {_format_time(last_heartbeat.observed_at if last_heartbeat else None)}")

        price_count = session.query(func.count(PriceObservation.id)).scalar() or 0
        avail_count = session.query(func.count(AvailabilityObservation.id)).scalar() or 0
        print(f"Price observations: {price_count:,}")
        print(f"Availability observations: {avail_count:,}")
        print()

        print("Collectors (most recent run):")
        collectors = (
            session.query(CollectorRun.collector_name)
            .distinct()
            .order_by(CollectorRun.collector_name)
            .all()
        )
        for (name,) in collectors:
            run = (
                session.query(CollectorRun)
                .filter_by(collector_name=name)
                .order_by(CollectorRun.started_at.desc())
                .first()
            )
            if run:
                print(
                    f"  {name}: {run.status} "
                    f"({_format_time(run.started_at)}) "
                    f"prices={run.price_rows_written} avail={run.availability_rows_written}"
                )
                if run.error_message:
                    print(f"    error: {run.error_message[:120]}")
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
    sys.exit(0)
