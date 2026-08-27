from __future__ import annotations

from pathlib import Path

import pytest

from data_platform.database import sqlite_url
from data_platform.lineage import LineageEmitter, database_namespace, source_dataset
from data_platform.orchestration import run_scheduled_partition
from data_platform.pipeline import run_pipeline

from .test_pipeline import order, write_orders


class RecordingClient:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event) -> None:
        self.events.append(event)


class FailingClient:
    def emit(self, event) -> None:
        raise ConnectionError("lineage backend unavailable")


def test_dataset_identity_preserves_sources_and_removes_database_credentials(
    tmp_path: Path,
) -> None:
    s3_dataset = source_dataset("s3://raw-bucket/orders/date=2026-08-25/orders.csv")
    local_dataset = source_dataset(tmp_path / "orders.csv")

    assert s3_dataset.namespace == "s3://raw-bucket"
    assert s3_dataset.name == "orders/date=2026-08-25/orders.csv"
    assert local_dataset.namespace == "file"
    assert local_dataset.name.endswith("orders.csv")
    assert database_namespace(
        "postgresql://platform:secret@database.internal:5432/data_platform?sslmode=require"
    ) == "postgresql://database.internal:5432/data_platform"


def test_warehouse_run_emits_start_and_complete_with_facets(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    database = tmp_path / "warehouse.db"
    write_orders(source, [order(), order(order_id="ORD-BAD", amount="-5")])
    client = RecordingClient()

    result = run_pipeline(
        source,
        database,
        lineage_input_uri="s3://raw-bucket/orders/date=2026-08-25/orders.csv",
        lineage_emitter=LineageEmitter(client, strict=True),
    )

    assert [event.eventType.value for event in client.events] == ["START", "COMPLETE"]
    start, complete = client.events
    assert start.run.runId == result["run_id"] == complete.run.runId
    assert start.job.namespace == "production-data-platform"
    assert start.job.name == "orders.warehouse_load"
    assert start.inputs[0].namespace == "s3://raw-bucket"
    assert start.inputs[0].name == "orders/date=2026-08-25/orders.csv"
    assert "schema" in start.inputs[0].facets
    assert {dataset.name for dataset in complete.outputs} >= {
        "fact_orders",
        "quarantined_orders",
        "pipeline_runs",
    }
    facts = next(dataset for dataset in complete.outputs if dataset.name == "fact_orders")
    quarantine = next(
        dataset for dataset in complete.outputs if dataset.name == "quarantined_orders"
    )
    assert facts.outputFacets["outputStatistics"].rowCount == 1
    assert quarantine.outputFacets["outputStatistics"].rowCount == 1
    assert "nominalTime" in complete.run.facets
    assert "jobType" in complete.job.facets
    assert "sourceCodeLocation" in complete.job.facets


def test_failed_run_emits_failure_details(tmp_path: Path) -> None:
    source = tmp_path / "invalid.csv"
    database = tmp_path / "warehouse.db"
    source.write_text("order_id,amount_usd\nORD-1,25.00\n", encoding="utf-8")
    client = RecordingClient()

    with pytest.raises(ValueError, match="missing required columns"):
        run_pipeline(
            source,
            database,
            lineage_emitter=LineageEmitter(client, strict=True),
        )

    assert [event.eventType.value for event in client.events] == ["START", "FAIL"]
    failure = client.events[-1]
    assert failure.run.runId == client.events[0].run.runId
    assert "missing required columns" in failure.run.facets["errorMessage"].message


def test_lineage_delivery_is_fail_open_by_default(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    database = tmp_path / "warehouse.db"
    write_orders(source, [order()])

    result = run_pipeline(
        source,
        database,
        lineage_emitter=LineageEmitter(FailingClient()),
    )

    assert result["status"] == "succeeded"


def test_airflow_execution_uses_distinct_lineage_job(tmp_path: Path) -> None:
    batch_date = "2026-08-25"
    source = tmp_path / f"date={batch_date}" / "orders.csv"
    source.parent.mkdir(parents=True)
    write_orders(source, [order()])
    client = RecordingClient()

    result = run_scheduled_partition(
        batch_date,
        source_template=str(tmp_path / "date={date}" / "orders.csv"),
        database_url=sqlite_url(tmp_path / "warehouse.db"),
        lineage_emitter=LineageEmitter(client, strict=True),
    )

    assert result["status"] == "succeeded"
    assert {event.job.name for event in client.events} == {"orders.airflow_partition"}
    assert {event.job.facets["jobType"].integration for event in client.events} == {
        "airflow"
    }
