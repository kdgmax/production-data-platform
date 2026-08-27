"""Apply ordered, version-controlled database migrations."""

from __future__ import annotations

from datetime import UTC, datetime

from .database import Database
from .sql_loader import read_sql

MIGRATION_VERSIONS = (1, 2)


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

    for version in MIGRATION_VERSIONS:
        if version in applied:
            continue

        filename = f"{version:03d}_" + ("core.sql" if version == 1 else "quality.sql")
        with database.transaction():
            database.execute_script(read_sql(database.dialect, filename))
            database.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(UTC)),
            )
        newly_applied.append(version)

    return newly_applied
