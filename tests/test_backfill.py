from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import data_platform.backfill as backfill_module
from data_platform.backfill import run_backfill
from data_platform.database import sqlite_url
from data_platform.locking import PipelineLockedError

from .test_pipeline import order, write_orders


def partition(template_root: Path, batch_date: date, order_id: str) -> None:
    path = template_root / f"date={batch_date.isoformat()}" / "orders.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_orders(path, [order(order_id=order_id)])


def scalar(database: Path, query: str):
    with sqlite3.connect(database) as connection:
        return connection.execute(query).fetchone()[0]


def test_backfill_processes_range_and_replay_is_safe(tmp_path: Path) -> None:
    partitions = tmp_path / "partitions"
    database = tmp_path / "warehouse.db"
    dates = [date(2026, 8, 25), date(2026, 8, 26), date(2026, 8, 27)]
    for index, batch_date in enumerate(dates, start=1):
        partition(partitions, batch_date, f"ORD-{index}")

    arguments = {
        "start_date": dates[0],
        "end_date": dates[-1],
        "source_template": str(partitions / "date={date}" / "orders.csv"),
        "database_url": sqlite_url(database),
        "retry_delay_seconds": 0,
    }
    first = run_backfill(**arguments)
    second = run_backfill(**arguments)

    assert first["succeeded_batches"] == 3
    assert second["succeeded_batches"] == 3
    assert scalar(database, "SELECT COUNT(*) FROM fact_orders") == 3
    assert scalar(database, "SELECT COUNT(*) FROM pipeline_runs") == 6
    assert scalar(
        database,
        "SELECT COUNT(*) FROM pipeline_runs WHERE trigger_type = 'backfill'",
    ) == 6


def test_backfill_can_continue_after_missing_partition(tmp_path: Path) -> None:
    partitions = tmp_path / "partitions"
    database = tmp_path / "warehouse.db"
    partition(partitions, date(2026, 8, 25), "ORD-1")

    result = run_backfill(
        start_date=date(2026, 8, 25),
        end_date=date(2026, 8, 26),
        source_template=str(partitions / "date={date}" / "orders.csv"),
        database_url=sqlite_url(database),
        retry_delay_seconds=0,
        continue_on_error=True,
    )

    assert result["status"] == "partial"
    assert result["succeeded_batches"] == 1
    assert result["failed_batches"] == 1
    assert scalar(database, "SELECT COUNT(*) FROM pipeline_runs WHERE status = 'failed'") == 1


def test_backfill_retries_transient_lock_failure(monkeypatch, tmp_path: Path) -> None:
    attempts = 0

    def flaky_pipeline(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PipelineLockedError("temporary contention")
        return {"run_id": "successful-retry"}

    monkeypatch.setattr(backfill_module, "run_pipeline", flaky_pipeline)

    result = run_backfill(
        start_date=date(2026, 8, 25),
        end_date=date(2026, 8, 25),
        source_template=str(tmp_path / "date={date}" / "orders.csv"),
        database_url="sqlite:///:memory:",
        retry_delay_seconds=0,
    )

    assert attempts == 2
    assert result["succeeded_batches"] == 1
    assert result["batches"][0]["attempts"] == 2
