"""Apply ordered, version-controlled database migrations."""

from __future__ import annotations

from datetime import UTC, datetime

from .database import Database
from .sql_loader import read_sql

MIGRATIONS = {
    1: "001_core.sql",
    2: "002_quality.sql",
    3: "003_orchestration.sql",
}


def apply_migrations(database: Database) -> list[int]:
    with database.transaction():
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )

    applied = {
        row[0] for row in database.execute("SELECT version FROM schema_migrations").fetchall()
    }
    newly_applied: list[int] = []

    for version, filename in MIGRATIONS.items():
        if version in applied:
            continue

        with database.transaction():
            database.execute_script(read_sql(database.dialect, filename))
            database.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(UTC)),
            )
        newly_applied.append(version)

    return newly_applied
