"""Rollup job entrypoint — run manually or from scheduler."""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from analysis.rollups import compute_rollups
from config import settings
from db.session import get_session
from logging_utils import log_extra, setup_logging

load_dotenv()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


def run_rollups() -> None:
    try:
        with get_session() as session:
            run = compute_rollups(session)
            log_extra(
                logger,
                logging.INFO,
                "rollup_completed",
                snapshot_at=run.snapshot_at.isoformat(),
                gpu_index_rows=run.gpu_index_rows,
                provider_snapshot_rows=run.provider_snapshot_rows,
                price_history_rows=run.price_history_rows,
                availability_daily_rows=run.availability_daily_rows,
            )
    except Exception as exc:
        log_extra(logger, logging.ERROR, "rollup_failed", error=str(exc))
        raise


def main() -> None:
    run_rollups()


if __name__ == "__main__":
    main()
    sys.exit(0)
