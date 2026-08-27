from pathlib import Path

from data_platform.database import sqlite_url
from data_platform.health import get_health_summary
from data_platform.pipeline import run_pipeline

from .test_pipeline import order, write_orders


def test_health_summary_reports_latest_run(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    database = tmp_path / "warehouse.db"
    write_orders(source, [order()])
    run_pipeline(source, database)

    health = get_health_summary(sqlite_url(database))

    assert health["status"] == "succeeded"
    assert health["accepted_rows"] == 1
    assert len(health["quality_checks"]) == 4
    assert all(check["passed"] for check in health["quality_checks"])
    assert health["source_file"] is None
