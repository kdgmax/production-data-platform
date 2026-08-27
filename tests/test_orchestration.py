from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from data_platform.database import sqlite_url
from data_platform.orchestration import (
    evaluate_scheduled_run,
    logical_batch_date,
    run_scheduled_partition,
    source_uri_for_batch,
)

from .test_pipeline import order, write_orders


def load_orders_dag():
    dag_path = Path(__file__).parents[1] / "dags" / "orders_daily.py"
    spec = importlib.util.spec_from_file_location("orders_daily_dag", dag_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.orders_daily


def test_airflow_dag_has_schedule_dependencies_and_retries(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AIRFLOW_HOME", str(tmp_path / "airflow"))
    dag = load_orders_dag()

    assert dag.dag_id == "orders_daily"
    assert dag.timetable.expression == "0 6 * * *"
    assert dag.catchup is True
    assert dag.max_active_runs == 1
    assert set(dag.task_ids) == {
        "resolve_partition",
        "process_partition",
        "evaluate_platform_slo",
    }
    assert dag.get_task("resolve_partition").downstream_task_ids == {"process_partition"}
    assert dag.get_task("process_partition").downstream_task_ids == {
        "evaluate_platform_slo"
    }

    processing_task = dag.get_task("process_partition")
    assert processing_task.retries == 3
    assert processing_task.retry_delay == timedelta(minutes=1)
    assert processing_task.retry_exponential_backoff is True
    assert processing_task.max_retry_delay == timedelta(minutes=15)


def test_scheduled_partition_runs_and_passes_slo(tmp_path: Path) -> None:
    batch_date = "2026-08-25"
    source = tmp_path / f"date={batch_date}" / "orders.csv"
    source.parent.mkdir(parents=True)
    write_orders(source, [order()])
    database_url = sqlite_url(tmp_path / "warehouse.db")

    result = run_scheduled_partition(
        batch_date,
        source_template=str(tmp_path / "date={date}" / "orders.csv"),
        database_url=database_url,
    )
    evaluation = evaluate_scheduled_run(
        result,
        database_url=database_url,
        success_slo_percent=95,
    )

    assert result["trigger_type"] == "airflow"
    assert evaluation["pipeline_status"] == "succeeded"
    assert evaluation["platform_status"] == "healthy"
    assert evaluation["success_rate_percent"] == 100.0


def test_orchestration_helpers_validate_dates_and_templates() -> None:
    assert logical_batch_date(date(2026, 8, 25)) == "2026-08-25"
    assert logical_batch_date(datetime(2026, 8, 25, 6, tzinfo=UTC)) == "2026-08-25"
    assert source_uri_for_batch("2026-08-25", "s3://bucket/date={date}/orders.csv") == (
        "s3://bucket/date=2026-08-25/orders.csv"
    )
    with pytest.raises(ValueError, match="must contain"):
        source_uri_for_batch("2026-08-25", "s3://bucket/orders.csv")


def test_airflow_compose_declares_isolated_metadata_and_platform_databases() -> None:
    project_root = Path(__file__).parents[1]
    compose = yaml.safe_load((project_root / "docker-compose.airflow.yml").read_text())

    assert set(compose["services"]) == {"postgres", "airflow"}
    airflow_environment = compose["services"]["airflow"]["environment"]
    assert airflow_environment["AIRFLOW__CORE__EXECUTOR"] == "LocalExecutor"
    assert airflow_environment["DATA_PLATFORM_DATABASE_URL"].endswith("/data_platform")
    assert airflow_environment["DATA_PLATFORM_OPENLINEAGE_ENABLED"] == "true"
    assert airflow_environment["OPENLINEAGE_CONFIG"].endswith("openlineage.yml")
    assert compose["services"]["postgres"]["environment"]["POSTGRES_DB"] == "airflow"
