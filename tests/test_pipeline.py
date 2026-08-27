from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

from data_platform.pipeline import run_pipeline

FIELDS = [
    "order_id",
    "customer_id",
    "order_ts",
    "status",
    "amount_usd",
    "source_updated_at",
]


def write_orders(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def order(
    order_id: str = "ORD-1",
    amount: str = "25.00",
    updated_at: str = "2026-08-25T10:05:00Z",
) -> dict[str, str]:
    return {
        "order_id": order_id,
        "customer_id": "CUST-1",
        "order_ts": "2026-08-25T10:00:00Z",
        "status": "completed",
        "amount_usd": amount,
        "source_updated_at": updated_at,
    }


def scalar(database: Path, query: str):
    with sqlite3.connect(database) as connection:
        return connection.execute(query).fetchone()[0]


def test_loads_valid_rows_and_quarantines_invalid_rows(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    database = tmp_path / "warehouse.db"
    write_orders(source, [order(), order(order_id="ORD-2", amount="-5")])

    metrics = run_pipeline(source, database)

    assert metrics["input_rows"] == 2
    assert metrics["accepted_rows"] == 1
    assert metrics["quarantined_rows"] == 1
    assert scalar(database, "SELECT COUNT(*) FROM fact_orders") == 1
    assert scalar(database, "SELECT COUNT(*) FROM quarantined_orders") == 1
    assert metrics["quality_checks_passed"] == 4
    assert scalar(database, "SELECT COUNT(*) FROM data_quality_results") == 4


def test_rerun_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    database = tmp_path / "warehouse.db"
    write_orders(source, [order()])

    run_pipeline(source, database)
    run_pipeline(source, database)

    assert scalar(database, "SELECT COUNT(*) FROM staging_orders") == 1
    assert scalar(database, "SELECT COUNT(*) FROM fact_orders") == 1
    assert scalar(database, "SELECT COUNT(*) FROM pipeline_runs") == 2


def test_newer_source_record_updates_existing_order(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    database = tmp_path / "warehouse.db"
    write_orders(source, [order(amount="25.00")])
    run_pipeline(source, database)

    write_orders(
        source,
        [order(amount="30.00", updated_at="2026-08-25T11:05:00Z")],
    )
    run_pipeline(source, database)

    assert scalar(database, "SELECT amount_usd FROM fact_orders WHERE order_id = 'ORD-1'") == 30.0


def test_batch_keeps_latest_duplicate(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    database = tmp_path / "warehouse.db"
    write_orders(
        source,
        [
            order(amount="25.00"),
            order(amount="40.00", updated_at="2026-08-25T12:05:00Z"),
        ],
    )

    metrics = run_pipeline(source, database)

    assert metrics["deduplicated_rows"] == 1
    assert scalar(database, "SELECT amount_usd FROM fact_orders WHERE order_id = 'ORD-1'") == 40.0


def test_schema_failure_is_recorded(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    database = tmp_path / "warehouse.db"
    source.write_text("order_id,amount_usd\nORD-1,25.00\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required columns"):
        run_pipeline(source, database)

    assert scalar(database, "SELECT COUNT(*) FROM pipeline_runs WHERE status = 'failed'") == 1
    assert "missing required columns" in scalar(
        database,
        "SELECT error_message FROM pipeline_runs WHERE status = 'failed'",
    )
