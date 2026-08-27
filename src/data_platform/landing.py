"""File manifest, checksum claiming, and exactly-once pipeline entry point."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .database import Database
from .migrations import apply_migrations
from .object_store import MaterializedObject, materialize_object
from .observability import configure_logging
from .pipeline import run_pipeline


class FileAlreadyClaimedError(RuntimeError):
    """Raised when another worker is already processing the same file content."""


@dataclass(frozen=True)
class FileIdentity:
    checksum_sha256: str
    size_bytes: int


def identify_file(path: Path) -> FileIdentity:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size_bytes += len(chunk)
    return FileIdentity(checksum_sha256=digest.hexdigest(), size_bytes=size_bytes)


def claim_file(
    database: Database,
    *,
    materialized: MaterializedObject,
    identity: FileIdentity,
    batch_date: date | None,
) -> tuple[str, str | None]:
    now = datetime.now(UTC)
    with database.transaction():
        inserted = database.execute(
            """
            INSERT INTO file_manifest (
                file_uri, checksum_sha256, size_bytes, etag, batch_date,
                status, discovered_at
            ) VALUES (?, ?, ?, ?, ?, 'processing', ?)
            ON CONFLICT(checksum_sha256) DO NOTHING
            """,
            (
                materialized.uri,
                identity.checksum_sha256,
                identity.size_bytes,
                materialized.etag,
                batch_date,
                now,
            ),
        )
        if inserted.rowcount == 1:
            return "claimed", None

        existing = database.execute(
            """
            SELECT status, run_id
            FROM file_manifest
            WHERE checksum_sha256 = ?
            """,
            (identity.checksum_sha256,),
        ).fetchone()

        if existing[0] == "succeeded":
            return "skipped", existing[1]
        if existing[0] == "processing":
            raise FileAlreadyClaimedError(
                f"file content is already being processed: {identity.checksum_sha256}"
            )

        database.execute(
            """
            UPDATE file_manifest
            SET file_uri = ?, size_bytes = ?, etag = ?, batch_date = ?,
                status = 'processing', discovered_at = ?, processed_at = NULL,
                run_id = NULL, error_message = NULL
            WHERE checksum_sha256 = ?
            """,
            (
                materialized.uri,
                identity.size_bytes,
                materialized.etag,
                batch_date,
                now,
                identity.checksum_sha256,
            ),
        )
        return "claimed", None


def finish_file(
    database_url: str,
    *,
    checksum_sha256: str,
    status: str,
    run_id: str | None = None,
    error_message: str | None = None,
) -> None:
    with Database.connect(database_url) as database, database.transaction():
        database.execute(
            """
            UPDATE file_manifest
            SET status = ?, processed_at = ?, run_id = ?, error_message = ?
            WHERE checksum_sha256 = ?
            """,
            (
                status,
                datetime.now(UTC),
                run_id,
                error_message,
                checksum_sha256,
            ),
        )


def process_source_file(
    *,
    source_uri: str,
    database_url: str,
    batch_date: date | None = None,
    trigger_type: str = "landing",
) -> dict[str, Any]:
    with materialize_object(source_uri) as materialized:
        identity = identify_file(materialized.path)

        with Database.connect(database_url) as database:
            apply_migrations(database)
            claim_status, existing_run_id = claim_file(
                database,
                materialized=materialized,
                identity=identity,
                batch_date=batch_date,
            )

        if claim_status == "skipped":
            return {
                "status": "skipped",
                "reason": "checksum_already_succeeded",
                "source_uri": source_uri,
                "checksum_sha256": identity.checksum_sha256,
                "run_id": existing_run_id,
            }

        try:
            metrics = run_pipeline(
                materialized.path,
                database_url=database_url,
                batch_date=batch_date,
                trigger_type=trigger_type,
            )
        # This boundary persists the file failure before propagating it to the caller.
        except Exception as error:
            finish_file(
                database_url,
                checksum_sha256=identity.checksum_sha256,
                status="failed",
                error_message=str(error),
            )
            raise

        finish_file(
            database_url,
            checksum_sha256=identity.checksum_sha256,
            status="succeeded",
            run_id=str(metrics["run_id"]),
        )
        return {
            **metrics,
            "source_uri": source_uri,
            "checksum_sha256": identity.checksum_sha256,
            "size_bytes": identity.size_bytes,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Process a local or S3 source object exactly once.")
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--batch-date", type=date.fromisoformat)
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATA_PLATFORM_DATABASE_URL", "sqlite:///warehouse.db"),
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    args = parser.parse_args()
    configure_logging(args.log_level)
    result = process_source_file(
        source_uri=args.source_uri,
        database_url=args.database_url,
        batch_date=args.batch_date,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
