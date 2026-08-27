from __future__ import annotations

import sqlite3
from pathlib import Path

import boto3
from moto import mock_aws

from data_platform.database import sqlite_url
from data_platform.landing import process_source_file

from .test_pipeline import order, write_orders


def scalar(database: Path, query: str):
    with sqlite3.connect(database) as connection:
        return connection.execute(query).fetchone()[0]


def test_duplicate_content_is_processed_exactly_once(tmp_path: Path) -> None:
    first_source = tmp_path / "first.csv"
    duplicate_source = tmp_path / "duplicate.csv"
    database = tmp_path / "warehouse.db"
    write_orders(first_source, [order()])
    duplicate_source.write_bytes(first_source.read_bytes())

    first = process_source_file(
        source_uri=str(first_source),
        database_url=sqlite_url(database),
    )
    duplicate = process_source_file(
        source_uri=str(duplicate_source),
        database_url=sqlite_url(database),
    )

    assert first["status"] == "succeeded"
    assert duplicate["status"] == "skipped"
    assert duplicate["run_id"] == first["run_id"]
    assert scalar(database, "SELECT COUNT(*) FROM file_manifest") == 1
    assert scalar(database, "SELECT COUNT(*) FROM pipeline_runs") == 1
    assert scalar(database, "SELECT COUNT(*) FROM fact_orders") == 1


@mock_aws
def test_s3_object_is_materialized_and_tracked(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    source = tmp_path / "orders.csv"
    database = tmp_path / "warehouse.db"
    write_orders(source, [order(order_id="ORD-S3")])

    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="data-platform-test")
    s3.put_object(
        Bucket="data-platform-test",
        Key="orders/date=2026-08-25/orders.csv",
        Body=source.read_bytes(),
    )

    result = process_source_file(
        source_uri="s3://data-platform-test/orders/date=2026-08-25/orders.csv",
        database_url=sqlite_url(database),
    )

    assert result["status"] == "succeeded"
    assert result["source_uri"].startswith("s3://")
    assert len(result["checksum_sha256"]) == 64
    assert scalar(database, "SELECT COUNT(*) FROM file_manifest WHERE status = 'succeeded'") == 1

