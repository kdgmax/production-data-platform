"""Runtime functions used by the Airflow orchestration layer."""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

from .landing import process_source_file
from .monitoring import get_monitoring_snapshot


def logical_batch_date(logical_date: date | datetime) -> str:
    if isinstance(logical_date, datetime):
        logical_date = logical_date.date()
    return logical_date.isoformat()


def source_uri_for_batch(batch_date: str, source_template: str) -> str:
    if "{date}" not in source_template:
        raise ValueError("source template must contain {date}")
    return source_template.format(date=batch_date)


def run_scheduled_partition(
    batch_date: str,
    *,
    source_template: str | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    source_template = source_template or os.getenv(
        "DATA_PLATFORM_SOURCE_TEMPLATE",
        "data/partitions/date={date}/orders.csv",
    )
    database_url = database_url or os.getenv(
        "DATA_PLATFORM_DATABASE_URL",
        "sqlite:///warehouse.db",
    )
    return process_source_file(
        source_uri=source_uri_for_batch(batch_date, source_template),
        database_url=database_url,
        batch_date=date.fromisoformat(batch_date),
        trigger_type="airflow",
    )


def evaluate_scheduled_run(
    result: dict[str, Any],
    *,
    database_url: str | None = None,
    success_slo_percent: float | None = None,
) -> dict[str, Any]:
    database_url = database_url or os.getenv(
        "DATA_PLATFORM_DATABASE_URL",
        "sqlite:///warehouse.db",
    )
    if success_slo_percent is None:
        success_slo_percent = float(os.getenv("DATA_PLATFORM_SUCCESS_SLO", "95"))

    snapshot = get_monitoring_snapshot(
        database_url,
        success_slo_percent=success_slo_percent,
    )
    run_id = result.get("run_id")
    recorded_run = next(
        (run for run in snapshot["recent_runs"] if run["run_id"] == run_id),
        None,
    )
    if recorded_run is None:
        raise RuntimeError(f"scheduled run is missing from monitoring history: {run_id}")
    if recorded_run["status"] != "succeeded":
        raise RuntimeError(f"scheduled run did not succeed: {run_id}")
    if snapshot["platform_status"] == "degraded":
        raise RuntimeError("platform SLO evaluation failed: " + "; ".join(snapshot["alerts"]))

    return {
        "run_id": run_id,
        "batch_date": result.get("batch_date"),
        "pipeline_status": recorded_run["status"],
        "platform_status": snapshot["platform_status"],
        "success_rate_percent": snapshot["overview"]["success_rate_percent"],
        "input_rows": recorded_run["input_rows"],
        "accepted_rows": recorded_run["accepted_rows"],
        "quarantined_rows": recorded_run["quarantined_rows"],
    }
