from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from data_platform.database import Database
from data_platform.pipeline import run_pipeline

from .test_pipeline import order, write_orders


def test_pipeline_runs_against_postgres(tmp_path: Path) -> None:
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is not configured")

    order_id = f"ORD-{uuid.uuid4()}"
    source = tmp_path / "orders.csv"
    write_orders(source, [order(order_id=order_id)])

    metrics = run_pipeline(source, database_url=database_url)

    with Database.connect(database_url) as database:
        fact_count = database.execute(
            "SELECT COUNT(*) FROM fact_orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()[0]

    assert metrics["accepted_rows"] == 1
    assert metrics["quality_checks_passed"] == 4
    assert fact_count == 1

