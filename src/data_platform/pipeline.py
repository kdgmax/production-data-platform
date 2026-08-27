"""An idempotent batch pipeline with validation, quarantine, and audit metrics."""

from __future__ import annotations

import csv
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .database import Database, sqlite_url
from .migrations import apply_migrations
from .quality import QualityResult, assert_quality, run_reconciliation_checks
from .sql_loader import read_sql

VALID_STATUSES = {"pending", "completed", "cancelled"}
LOGGER = logging.getLogger(__name__)
REQUIRED_COLUMNS = {
    "order_id",
    "customer_id",
    "order_ts",
    "status",
    "amount_usd",
    "source_updated_at",
}


@dataclass(frozen=True)
class Order:
    order_id: str
    customer_id: str
    order_ts: datetime
    status: str
    amount_usd: float
    source_updated_at: datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_iso8601(value: str) -> datetime:
    """Validate an ISO-8601 timestamp and return a normalized UTC value."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def validate_row(row: dict[str, str]) -> tuple[Order | None, list[str]]:
    errors: list[str] = []

    for field in ("order_id", "customer_id"):
        if not row.get(field, "").strip():
            errors.append(f"{field} is required")

    status = row.get("status", "").strip().lower()
    if status not in VALID_STATUSES:
        errors.append(f"status must be one of {sorted(VALID_STATUSES)}")

    try:
        amount = float(row.get("amount_usd", ""))
        if amount < 0:
            errors.append("amount_usd must be non-negative")
    except ValueError:
        amount = 0.0
        errors.append("amount_usd must be numeric")

    normalized_timestamps: dict[str, datetime] = {}
    for field in ("order_ts", "source_updated_at"):
        try:
            normalized_timestamps[field] = parse_iso8601(row.get(field, ""))
        except ValueError:
            errors.append(f"{field} must be an ISO-8601 timestamp with a timezone")

    if errors:
        return None, errors

    return (
        Order(
            order_id=row["order_id"].strip(),
            customer_id=row["customer_id"].strip(),
            order_ts=normalized_timestamps["order_ts"],
            status=status,
            amount_usd=round(amount, 2),
            source_updated_at=normalized_timestamps["source_updated_at"],
        ),
        [],
    )


def read_and_validate(input_path: Path) -> tuple[list[Order], list[tuple[dict, list[str]]], int]:
    valid_by_order_id: dict[str, Order] = {}
    quarantined: list[tuple[dict, list[str]]] = []
    valid_rows_seen = 0

    with input_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(f"input is missing required columns: {sorted(missing_columns)}")

        for row in reader:
            order, errors = validate_row(row)
            if errors:
                quarantined.append((row, errors))
                continue

            valid_rows_seen += 1
            assert order is not None
            existing = valid_by_order_id.get(order.order_id)
            if existing is None or order.source_updated_at > existing.source_updated_at:
                valid_by_order_id[order.order_id] = order

    deduplicated_rows = valid_rows_seen - len(valid_by_order_id)
    return list(valid_by_order_id.values()), quarantined, deduplicated_rows


def load_staging(database: Database, orders: list[Order]) -> None:
    database.executemany(
        """
        INSERT INTO staging_orders (
            order_id, customer_id, order_ts, status, amount_usd, source_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(order_id) DO UPDATE SET
            customer_id = excluded.customer_id,
            order_ts = excluded.order_ts,
            status = excluded.status,
            amount_usd = excluded.amount_usd,
            source_updated_at = excluded.source_updated_at
        WHERE excluded.source_updated_at > staging_orders.source_updated_at;
        """,
        [
            (
                order.order_id,
                order.customer_id,
                order.order_ts,
                order.status,
                order.amount_usd,
                order.source_updated_at,
            )
            for order in orders
        ],
    )


def transform_warehouse(database: Database) -> None:
    database.execute_script(read_sql(database.dialect, "transform.sql"))


def store_quality_results(
    database: Database,
    run_id: str,
    results: list[QualityResult],
) -> None:
    database.executemany(
        """
        INSERT INTO data_quality_results (
            run_id, check_name, violation_count, passed, checked_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            (run_id, result.check_name, result.violation_count, result.passed, utc_now())
            for result in results
        ],
    )


def store_run(
    database: Database,
    *,
    run_id: str,
    started_at: datetime,
    input_rows: int,
    accepted_rows: int,
    quarantined_rows: int,
    deduplicated_rows: int,
    status: str,
    error_message: str | None = None,
) -> None:
    database.execute(
        """
        INSERT INTO pipeline_runs (
            run_id, started_at, completed_at, input_rows, accepted_rows,
            quarantined_rows, deduplicated_rows, status, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            started_at,
            utc_now(),
            input_rows,
            accepted_rows,
            quarantined_rows,
            deduplicated_rows,
            status,
            error_message,
        ),
    )


def run_pipeline(
    input_path: Path,
    database_path: Path | None = None,
    *,
    database_url: str | None = None,
) -> dict[str, int | str]:
    """Run one atomic batch and return auditable pipeline metrics."""
    run_id = str(uuid.uuid4())
    started_at = utc_now()
    input_rows = 0
    accepted_rows = 0
    quarantined_rows = 0
    deduplicated_rows = 0

    LOGGER.info("Pipeline started", extra={"event": "pipeline_started", "run_id": run_id})

    if database_url is not None and database_path is not None:
        raise ValueError("provide database_path or database_url, not both")
    if database_url is None:
        database_url = sqlite_url(database_path or Path("warehouse.db"))

    with Database.connect(database_url) as database:
        apply_migrations(database)
        try:
            orders, quarantined, deduplicated_rows = read_and_validate(input_path)
            accepted_rows = len(orders)
            quarantined_rows = len(quarantined)
            input_rows = accepted_rows + quarantined_rows + deduplicated_rows

            with database.transaction():
                load_staging(database, orders)
                transform_warehouse(database)

                database.executemany(
                    """
                    INSERT INTO quarantined_orders (
                        run_id, raw_payload, error_reason, quarantined_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    [
                        (run_id, json.dumps(row, sort_keys=True), "; ".join(errors), utc_now())
                        for row, errors in quarantined
                    ],
                )

                quality_results = run_reconciliation_checks(database)
                assert_quality(quality_results)
                store_quality_results(database, run_id, quality_results)
                store_run(
                    database,
                    run_id=run_id,
                    started_at=started_at,
                    input_rows=input_rows,
                    accepted_rows=accepted_rows,
                    quarantined_rows=quarantined_rows,
                    deduplicated_rows=deduplicated_rows,
                    status="succeeded",
                )
        except Exception as error:
            with database.transaction():
                store_run(
                    database,
                    run_id=run_id,
                    started_at=started_at,
                    input_rows=input_rows,
                    accepted_rows=accepted_rows,
                    quarantined_rows=quarantined_rows,
                    deduplicated_rows=deduplicated_rows,
                    status="failed",
                    error_message=str(error),
                )
            LOGGER.exception(
                "Pipeline failed",
                extra={
                    "event": "pipeline_failed",
                    "run_id": run_id,
                    "error_type": type(error).__name__,
                },
            )
            raise

    quality_checks_passed = len(quality_results)
    LOGGER.info(
        "Pipeline succeeded",
        extra={
            "event": "pipeline_succeeded",
            "run_id": run_id,
            "input_rows": input_rows,
            "accepted_rows": accepted_rows,
            "quarantined_rows": quarantined_rows,
            "deduplicated_rows": deduplicated_rows,
            "quality_checks_passed": quality_checks_passed,
        },
    )

    return {
        "run_id": run_id,
        "status": "succeeded",
        "input_rows": input_rows,
        "accepted_rows": accepted_rows,
        "quarantined_rows": quarantined_rows,
        "deduplicated_rows": deduplicated_rows,
        "quality_checks_passed": quality_checks_passed,
    }
