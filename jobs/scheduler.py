"""APScheduler entrypoint — long-running collector scheduler."""

from __future__ import annotations

import logging
import os
import signal
import sys
from datetime import UTC, datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

from collectors.base import BaseCollector
from collectors.lambda_labs import LambdaLabsCollector
from collectors.runpod import RunPodCollector
from collectors.skypilot_catalog import SkyPilotCatalogCollector
from collectors.vast import VastCollector
from config import settings
from db.models import CollectorRun, SchedulerHeartbeat
from db.session import get_session
from jobs.rollup_job import run_rollups
from logging_utils import log_extra, setup_logging

load_dotenv()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

COLLECTORS: list[BaseCollector] = [
    SkyPilotCatalogCollector(),
    VastCollector(),
    RunPodCollector(),
    LambdaLabsCollector(),
]


def run_collector(collector: BaseCollector) -> None:
    started_at = datetime.now(UTC)
    status = "success"
    error_message: str | None = None
    price_rows = 0
    availability_rows = 0

    try:
        with get_session() as session:
            price_rows, availability_rows = collector.run(session)
            session.add(
                CollectorRun(
                    collector_name=collector.name,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    status=status,
                    price_rows_written=price_rows,
                    availability_rows_written=availability_rows,
                )
            )
    except Exception as exc:
        status = "error"
        error_message = str(exc)
        log_extra(
            logger,
            logging.ERROR,
            "collector_run_exception",
            collector=collector.name,
            error=error_message,
        )
        try:
            with get_session() as session:
                session.add(
                    CollectorRun(
                        collector_name=collector.name,
                        started_at=started_at,
                        finished_at=datetime.now(UTC),
                        status=status,
                        price_rows_written=price_rows,
                        availability_rows_written=availability_rows,
                        error_message=error_message[:2000],
                    )
                )
        except Exception as inner:
            log_extra(
                logger,
                logging.ERROR,
                "collector_run_log_failed",
                collector=collector.name,
                error=str(inner),
            )


def run_all_collectors() -> None:
    log_extra(logger, logging.INFO, "collector_cycle_started")
    for collector in COLLECTORS:
        run_collector(collector)
    log_extra(logger, logging.INFO, "collector_cycle_finished")


def record_heartbeat() -> None:
    try:
        with get_session() as session:
            session.add(
                SchedulerHeartbeat(
                    observed_at=datetime.now(UTC),
                    process_id=os.getpid(),
                    message="alive",
                )
            )
    except Exception as exc:
        log_extra(
            logger,
            logging.ERROR,
            "heartbeat_failed",
            error=str(exc),
        )


def main() -> None:
    log_extra(
        logger,
        logging.INFO,
        "scheduler_starting",
        interval_minutes=settings.collector_interval_minutes,
        collectors=[c.name for c in COLLECTORS],
    )

    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        run_all_collectors,
        trigger=IntervalTrigger(minutes=settings.collector_interval_minutes),
        id="collectors",
        name="Run all collectors",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )

    scheduler.add_job(
        record_heartbeat,
        trigger=IntervalTrigger(minutes=5),
        id="heartbeat",
        name="Scheduler heartbeat",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )

    scheduler.add_job(
        run_rollups,
        trigger=IntervalTrigger(minutes=settings.collector_interval_minutes),
        id="rollups",
        name="Compute snapshot rollups",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )

    def shutdown(signum, frame) -> None:
        log_extra(logger, logging.INFO, "scheduler_shutting_down", signal=signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    record_heartbeat()
    scheduler.start()


if __name__ == "__main__":
    main()
