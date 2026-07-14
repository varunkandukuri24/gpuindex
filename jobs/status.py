"""CLI status command — last poll, row counts, DB size."""

from __future__ import annotations

import sys

from dotenv import load_dotenv

from db.session import SessionLocal, engine
from jobs.status_data import collect_status

load_dotenv()


def main() -> None:
    session = SessionLocal()
    try:
        data = collect_status(session)
        print("GPU Pulse — Status")
        print("=" * 40)
        print(f"Database: {data['database_url']}")
        if data["db_size_bytes"] is not None:
            print(f"DB size: {data['db_size_bytes']:,} bytes")
        print(f"Last scheduler heartbeat: {data['last_heartbeat_fmt']}")
        print(f"Price observations: {data['price_observations']:,}")
        print(f"Availability observations: {data['availability_observations']:,}")
        print()
        print("Collectors (most recent run):")
        for row in data["collectors"]:
            print(
                f"  {row['name']}: {row['status']} "
                f"({row['started_at_fmt']}) "
                f"prices={row['price_rows_written']} "
                f"avail={row['availability_rows_written']}"
            )
            if row["error_message"]:
                print(f"    error: {row['error_message'][:120]}")
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
    sys.exit(0)
