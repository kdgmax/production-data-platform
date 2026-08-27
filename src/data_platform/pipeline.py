"""An idempotent batch pipeline with validation, quarantine, and audit metrics."""

from __future__ import annotations

import csv
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

VALID_STATUSES = {"pending", "completed", "cancelled"}
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
    order_ts: str
    status: str
    amount_usd: float
    source_updated_at: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso8601(value: str) -> str:
    """Validate an ISO-8601 timestamp and return a normalized UTC value."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC).isoformat()


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

    normalized_timestamps: dict[str, str] = {}
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


def initialize_warehouse(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS staging_orders (
            order_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            order_ts TEXT NOT NULL,
            status TEXT NOT NULL,
            amount_usd REAL NOT NULL CHECK (amount_usd >= 0),
            source_updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dim_customers (
            customer_sk INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id TEXT NOT NULL UNIQUE,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fact_orders (
            order_id TEXT PRIMARY KEY,
            customer_sk INTEGER NOT NULL,
            order_ts TEXT NOT NULL,
            status TEXT NOT NULL,
            amount_usd REAL NOT NULL,
            source_updated_at TEXT NOT NULL,
            FOREIGN KEY (customer_sk) REFERENCES dim_customers(customer_sk)
        );

        CREATE TABLE IF NOT EXISTS quarantined_orders (
            quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            raw_payload TEXT NOT NULL,
            error_reason TEXT NOT NULL,
            quarantined_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            input_rows INTEGER NOT NULL,
            accepted_rows INTEGER NOT NULL,
            quarantined_rows INTEGER NOT NULL,
            deduplicated_rows INTEGER NOT NULL,
            status TEXT NOT NULL
        );
        """
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


def load_staging(connection: sqlite3.Connection, orders: list[Order]) -> None:
    connection.executemany(
        """
        INSERT INTO staging_orders (
            order_id, customer_id, order_ts, status, amount_usd, source_updated_at
        ) VALUES (
            :order_id, :customer_id, :order_ts, :status, :amount_usd, :source_updated_at
        )
        ON CONFLICT(order_id) DO UPDATE SET
            customer_id = excluded.customer_id,
            order_ts = excluded.order_ts,
            status = excluded.status,
            amount_usd = excluded.amount_usd,
            source_updated_at = excluded.source_updated_at
        WHERE excluded.source_updated_at > staging_orders.source_updated_at;
        """,
        [asdict(order) for order in orders],
    )


def transform_warehouse(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        INSERT INTO dim_customers (customer_id, first_seen_at, last_seen_at)
        SELECT customer_id, MIN(order_ts), MAX(order_ts)
        FROM staging_orders
        GROUP BY customer_id
        ON CONFLICT(customer_id) DO UPDATE SET
            first_seen_at = MIN(dim_customers.first_seen_at, excluded.first_seen_at),
            last_seen_at = MAX(dim_customers.last_seen_at, excluded.last_seen_at);

        INSERT INTO fact_orders (
            order_id, customer_sk, order_ts, status, amount_usd, source_updated_at
        )
        SELECT
            source.order_id,
            customer.customer_sk,
            source.order_ts,
            source.status,
            source.amount_usd,
            source.source_updated_at
        FROM staging_orders AS source
        JOIN dim_customers AS customer USING (customer_id)
        ON CONFLICT(order_id) DO UPDATE SET
            customer_sk = excluded.customer_sk,
            order_ts = excluded.order_ts,
            status = excluded.status,
            amount_usd = excluded.amount_usd,
            source_updated_at = excluded.source_updated_at
        WHERE excluded.source_updated_at > fact_orders.source_updated_at;
        """
    )


def run_pipeline(input_path: Path, database_path: Path) -> dict[str, int | str]:
    """Run one atomic batch and return auditable pipeline metrics."""
    run_id = str(uuid.uuid4())
    started_at = utc_now()
    orders, quarantined, deduplicated_rows = read_and_validate(input_path)
    input_rows = len(orders) + len(quarantined) + deduplicated_rows

    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        initialize_warehouse(connection)
        with connection:
            load_staging(connection, orders)
            transform_warehouse(connection)

            connection.executemany(
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

            completed_at = utc_now()
            connection.execute(
                """
                INSERT INTO pipeline_runs (
                    run_id, started_at, completed_at, input_rows, accepted_rows,
                    quarantined_rows, deduplicated_rows, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    started_at,
                    completed_at,
                    input_rows,
                    len(orders),
                    len(quarantined),
                    deduplicated_rows,
                    "succeeded",
                ),
            )

    return {
        "run_id": run_id,
        "status": "succeeded",
        "input_rows": input_rows,
        "accepted_rows": len(orders),
        "quarantined_rows": len(quarantined),
        "deduplicated_rows": deduplicated_rows,
    }
