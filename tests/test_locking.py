from pathlib import Path

import pytest

from data_platform.database import Database, sqlite_url
from data_platform.locking import PipelineLockedError, acquire_lock, release_lock
from data_platform.migrations import apply_migrations
from data_platform.pipeline import run_pipeline

from .test_pipeline import order, write_orders


def test_concurrent_pipeline_is_blocked(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    database_path = tmp_path / "warehouse.db"
    database_url = sqlite_url(database_path)
    write_orders(source, [order()])

    with Database.connect(database_url) as database:
        apply_migrations(database)
        acquire_lock(
            database,
            lock_name="orders_pipeline",
            owner_run_id="existing-run",
            ttl_seconds=3600,
        )

    with pytest.raises(PipelineLockedError, match="already held"):
        run_pipeline(source, database_url=database_url)

    with Database.connect(database_url) as database:
        release_lock(
            database,
            lock_name="orders_pipeline",
            owner_run_id="existing-run",
        )

