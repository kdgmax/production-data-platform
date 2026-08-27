"""Report the latest pipeline run and its quality checks."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from typing import Any

from .database import Database
from .migrations import apply_migrations


def serialize(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def get_health_summary(database_url: str) -> dict[str, Any]:
    with Database.connect(database_url) as database:
        apply_migrations(database)
        latest = database.execute(
            """
            SELECT run_id, completed_at, status, input_rows, accepted_rows,
                   quarantined_rows, deduplicated_rows, error_message,
                   batch_date, trigger_type
            FROM pipeline_runs
            ORDER BY completed_at DESC
            LIMIT 1
            """
        ).fetchone()

        if latest is None:
            return {"status": "no_runs"}

        run_id = latest[0]
        checks = database.execute(
            """
            SELECT check_name, violation_count, passed
            FROM data_quality_results
            WHERE run_id = ?
            ORDER BY check_name
            """,
            (run_id,),
        ).fetchall()

    return {
        "run_id": run_id,
        "completed_at": serialize(latest[1]),
        "status": latest[2],
        "input_rows": latest[3],
        "accepted_rows": latest[4],
        "quarantined_rows": latest[5],
        "deduplicated_rows": latest[6],
        "error_message": latest[7],
        "batch_date": serialize(latest[8]),
        "trigger_type": latest[9],
        "quality_checks": [
            {"name": row[0], "violations": row[1], "passed": bool(row[2])}
            for row in checks
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Show health for the latest pipeline run.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATA_PLATFORM_DATABASE_URL", "sqlite:///warehouse.db"),
    )
    args = parser.parse_args()
    print(json.dumps(get_health_summary(args.database_url), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
