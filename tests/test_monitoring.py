from __future__ import annotations

import csv
from pathlib import Path

import pytest

from data_platform.database import Database, sqlite_url
from data_platform.landing import process_source_file
from data_platform.monitoring import get_monitoring_snapshot
from data_platform.pipeline import run_pipeline, utc_now

from .test_pipeline import order, write_orders


def test_monitoring_snapshot_reports_runs_files_and_alerts(tmp_path: Path) -> None:
    valid_source = tmp_path / "valid.csv"
    invalid_source = tmp_path / "invalid.csv"
    database_path = tmp_path / "warehouse.db"
    database_url = sqlite_url(database_path)
    write_orders(valid_source, [order()])

    process_source_file(source_uri=str(valid_source), database_url=database_url)
    with invalid_source.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=["order_id"])
        writer.writeheader()
        writer.writerow({"order_id": "ORD-BAD"})

    with pytest.raises(ValueError, match="missing required columns"):
        run_pipeline(invalid_source, database_url=database_url)

    with Database.connect(database_url) as database, database.transaction():
        failed_run_id = database.execute(
            "SELECT run_id FROM pipeline_runs WHERE status = 'failed' LIMIT 1"
        ).fetchone()[0]
        database.execute(
            """
            INSERT INTO data_quality_results (
                run_id, check_name, violation_count, passed, checked_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (failed_run_id, "test_failure", 2, False, utc_now()),
        )

    snapshot = get_monitoring_snapshot(database_url)

    assert snapshot["platform_status"] == "degraded"
    assert snapshot["overview"] == {
        "total_runs": 2,
        "succeeded_runs": 1,
        "failed_runs": 1,
        "success_rate_percent": 50.0,
        "total_input_rows": 1,
        "accepted_rows": 1,
        "quarantined_rows": 0,
        "quarantine_rate_percent": 0.0,
        "deduplicated_rows": 0,
        "total_files": 1,
        "failed_files": 0,
    }
    assert snapshot["manifest_status"] == [
        {"status": "succeeded", "files": 1, "size_bytes": valid_source.stat().st_size}
    ]
    assert snapshot["quality_failures"][0]["check_name"] == "test_failure"
    assert snapshot["quality_failures"][0]["violations"] == 2
    assert {row["status"] for row in snapshot["recent_runs"]} == {"succeeded", "failed"}
    assert sum(row["runs"] for row in snapshot["daily_trends"]) == 2
    assert any("below the 95.00% SLO" in alert for alert in snapshot["alerts"])


def test_monitoring_snapshot_handles_empty_database(tmp_path: Path) -> None:
    snapshot = get_monitoring_snapshot(sqlite_url(tmp_path / "empty.db"))

    assert snapshot["platform_status"] == "no_runs"
    assert snapshot["overview"]["total_runs"] == 0
    assert snapshot["alerts"] == []


def test_monitoring_validates_inputs(tmp_path: Path) -> None:
    database_url = sqlite_url(tmp_path / "warehouse.db")

    with pytest.raises(ValueError, match="recent_limit"):
        get_monitoring_snapshot(database_url, recent_limit=0)
    with pytest.raises(ValueError, match="success_slo_percent"):
        get_monitoring_snapshot(database_url, success_slo_percent=101)


def test_streamlit_dashboard_renders(monkeypatch, tmp_path: Path) -> None:
    from streamlit.testing.v1 import AppTest

    database_url = sqlite_url(tmp_path / "dashboard.db")
    monkeypatch.setenv("DATA_PLATFORM_DATABASE_URL", database_url)
    dashboard_path = Path(__file__).parents[1] / "src" / "data_platform" / "dashboard.py"

    app = AppTest.from_file(str(dashboard_path)).run(timeout=20)

    assert not app.exception
    assert len(app.metric) == 8
    assert len(app.tabs) == 4
    assert any(message.value == "Platform status: no pipeline runs recorded" for message in app.info)
