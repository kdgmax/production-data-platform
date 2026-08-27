"""Date-range orchestration with safe replay and bounded retries."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import psycopg

from .locking import PipelineLockedError
from .observability import configure_logging
from .pipeline import run_pipeline

RETRYABLE_ERRORS = (PipelineLockedError, sqlite3.OperationalError, psycopg.OperationalError)


@dataclass(frozen=True)
class BatchResult:
    batch_date: str
    status: str
    attempts: int
    run_id: str | None = None
    error: str | None = None


def iter_dates(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def run_backfill(
    *,
    start_date: date,
    end_date: date,
    source_template: str,
    database_url: str,
    max_attempts: int = 3,
    retry_delay_seconds: float = 1.0,
    continue_on_error: bool = False,
) -> dict[str, Any]:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if "{date}" not in source_template:
        raise ValueError("source_template must contain {date}")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    results: list[BatchResult] = []

    for batch_date in iter_dates(start_date, end_date):
        source_path = Path(source_template.format(date=batch_date.isoformat()))
        attempt = 0

        while True:
            attempt += 1
            try:
                metrics = run_pipeline(
                    source_path,
                    database_url=database_url,
                    batch_date=batch_date,
                    trigger_type="backfill",
                )
                results.append(
                    BatchResult(
                        batch_date=batch_date.isoformat(),
                        status="succeeded",
                        attempts=attempt,
                        run_id=str(metrics["run_id"]),
                    )
                )
                break
            except RETRYABLE_ERRORS as error:
                if attempt >= max_attempts:
                    results.append(
                        BatchResult(
                            batch_date=batch_date.isoformat(),
                            status="failed",
                            attempts=attempt,
                            error=str(error),
                        )
                    )
                    break
                time.sleep(retry_delay_seconds * (2 ** (attempt - 1)))
            # The orchestration boundary records non-retryable batch failures in its summary.
            except Exception as error:  # noqa: BLE001
                results.append(
                    BatchResult(
                        batch_date=batch_date.isoformat(),
                        status="failed",
                        attempts=attempt,
                        error=str(error),
                    )
                )
                break

        if results[-1].status == "failed" and not continue_on_error:
            break

    succeeded = sum(result.status == "succeeded" for result in results)
    failed = sum(result.status == "failed" for result in results)
    status = "succeeded" if failed == 0 else ("partial" if succeeded else "failed")

    return {
        "status": status,
        "requested_batches": (end_date - start_date).days + 1,
        "processed_batches": len(results),
        "succeeded_batches": succeeded,
        "failed_batches": failed,
        "batches": [asdict(result) for result in results],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a date range of partitioned order files.")
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--source-template",
        default="data/partitions/date={date}/orders.csv",
        help="File path containing a {date} placeholder.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATA_PLATFORM_DATABASE_URL", "sqlite:///warehouse.db"),
    )
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    args = parser.parse_args()
    configure_logging(args.log_level)

    result = run_backfill(
        start_date=args.start_date,
        end_date=args.end_date,
        source_template=args.source_template,
        database_url=args.database_url,
        max_attempts=args.max_attempts,
        retry_delay_seconds=args.retry_delay_seconds,
        continue_on_error=args.continue_on_error,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["failed_batches"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
