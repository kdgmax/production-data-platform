"""Database-backed mutual exclusion for pipeline runs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .database import Database


class PipelineLockedError(RuntimeError):
    """Raised when another process owns the requested pipeline lock."""


def acquire_lock(
    database: Database,
    *,
    lock_name: str,
    owner_run_id: str,
    ttl_seconds: int,
) -> None:
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=ttl_seconds)

    try:
        with database.transaction():
            database.execute("DELETE FROM pipeline_locks WHERE expires_at <= ?", (now,))
            database.execute(
                """
                INSERT INTO pipeline_locks (
                    lock_name, owner_run_id, acquired_at, expires_at
                ) VALUES (?, ?, ?, ?)
                """,
                (lock_name, owner_run_id, now, expires_at),
            )
    except Exception as error:
        raise PipelineLockedError(f"pipeline lock is already held: {lock_name}") from error


def release_lock(database: Database, *, lock_name: str, owner_run_id: str) -> None:
    with database.transaction():
        database.execute(
            "DELETE FROM pipeline_locks WHERE lock_name = ? AND owner_run_id = ?",
            (lock_name, owner_run_id),
        )

