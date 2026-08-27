from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("pyspark")

from pyspark.sql import SparkSession

from data_platform.database import sqlite_url
from data_platform.lineage import LineageEmitter
from data_platform.spark_pipeline import process_spark_source_file

from .test_pipeline import order, write_orders


def scalar(database: Path, query: str):
    with sqlite3.connect(database) as connection:
        return connection.execute(query).fetchone()[0]


class RecordingClient:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event) -> None:
        self.events.append(event)


def test_spark_partitions_valid_and_quarantined_rows(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    output = tmp_path / "lake"
    database = tmp_path / "warehouse.db"
    missing_identifiers = order(order_id="ORD-MISSING")
    missing_identifiers["customer_id"] = ""
    missing_identifiers["status"] = ""
    write_orders(
        source,
        [
            order(amount="25.00"),
            order(amount="40.00", updated_at="2026-08-25T12:05:00Z"),
            order(order_id="ORD-BAD", amount="-5"),
            missing_identifiers,
        ],
    )
    lineage_client = RecordingClient()

    result = process_spark_source_file(
        source_uri=str(source),
        output_root=output,
        database_url=sqlite_url(database),
        batch_date=date(2026, 8, 25),
        lineage_emitter=LineageEmitter(lineage_client, strict=True),
    )

    assert result["input_rows"] == 4
    assert result["accepted_rows"] == 1
    assert result["quarantined_rows"] == 2
    assert result["deduplicated_rows"] == 1
    assert result["quality_checks_passed"] == 4
    assert [event.eventType.value for event in lineage_client.events] == [
        "START",
        "COMPLETE",
    ]
    assert {event.job.name for event in lineage_client.events} == {
        "orders.spark_transform"
    }
    assert lineage_client.events[-1].outputs[0].outputFacets[
        "outputStatistics"
    ].rowCount == 1

    spark = SparkSession.builder.master("local[1]").appName("verify-output").getOrCreate()
    try:
        accepted = spark.read.parquet(str(output / "accepted_orders"))
        quarantined = spark.read.parquet(str(output / "quarantined_orders"))
        assert accepted.select("amount_usd").first()[0] == 40
        assert accepted.select("batch_date").first()[0].isoformat() == "2026-08-25"
        errors = {row[0] for row in quarantined.select("error_reason").collect()}
        assert "amount_usd must be non-negative" in errors
        assert "customer_id is required; status is invalid" in errors
    finally:
        spark.stop()

    assert scalar(database, "SELECT COUNT(*) FROM pipeline_runs WHERE trigger_type = 'spark'") == 1
    assert scalar(database, "SELECT COUNT(*) FROM data_quality_results") == 4
    assert scalar(database, "SELECT COUNT(*) FROM file_manifest WHERE status = 'succeeded'") == 1


def test_spark_skips_duplicate_file_content(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    duplicate = tmp_path / "orders-copy.csv"
    output = tmp_path / "lake"
    database = tmp_path / "warehouse.db"
    write_orders(source, [order()])
    duplicate.write_bytes(source.read_bytes())

    first = process_spark_source_file(
        source_uri=str(source),
        output_root=output,
        database_url=sqlite_url(database),
        batch_date=date(2026, 8, 25),
    )
    second = process_spark_source_file(
        source_uri=str(duplicate),
        output_root=output,
        database_url=sqlite_url(database),
        batch_date=date(2026, 8, 25),
    )

    assert first["status"] == "succeeded"
    assert second["status"] == "skipped"
    assert second["run_id"] == first["run_id"]
    assert scalar(database, "SELECT COUNT(*) FROM pipeline_runs") == 1
