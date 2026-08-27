"""Portable historical monitoring queries for pipelines and landed files."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from .database import Database
from .health import serialize
from .migrations import apply_migrations


def _date_key(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _duration_seconds(started_at: date | datetime | str, completed_at: date | datetime | str) -> float:
    if isinstance(started_at, str):
        started_at = datetime.fromisoformat(started_at)
    if isinstance(completed_at, str):
        completed_at = datetime.fromisoformat(completed_at)
    return round((completed_at - started_at).total_seconds(), 3)


def get_monitoring_snapshot(
    database_url: str,
    *,
    recent_limit: int = 50,
    success_slo_percent: float = 95.0,
) -> dict[str, Any]:
    if recent_limit < 1:
        raise ValueError("recent_limit must be at least 1")
    if not 0 <= success_slo_percent <= 100:
        raise ValueError("success_slo_percent must be between 0 and 100")

    with Database.connect(database_url) as database:
        apply_migrations(database)
        run_rows = database.execute(
            """
            SELECT run_id, started_at, completed_at, status, input_rows,
                   accepted_rows, quarantined_rows, deduplicated_rows,
                   error_message, batch_date, trigger_type
            FROM pipeline_runs
            ORDER BY completed_at DESC, run_id DESC
            """
        ).fetchall()
        manifest_rows = database.execute(
            """
            SELECT status, COUNT(*), COALESCE(SUM(size_bytes), 0)
            FROM file_manifest
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()
        quality_rows = database.execute(
            """
            SELECT q.run_id, q.check_name, q.violation_count, q.checked_at,
                   r.trigger_type, r.batch_date
            FROM data_quality_results q
            JOIN pipeline_runs r ON r.run_id = q.run_id
            WHERE q.passed = ?
            ORDER BY q.checked_at DESC
            """,
            (False,),
        ).fetchall()

    total_runs = len(run_rows)
    succeeded_runs = sum(row[3] == "succeeded" for row in run_rows)
    failed_runs = total_runs - succeeded_runs
    total_input_rows = sum(row[4] for row in run_rows)
    accepted_rows = sum(row[5] for row in run_rows)
    quarantined_rows = sum(row[6] for row in run_rows)
    deduplicated_rows = sum(row[7] for row in run_rows)
    success_rate = round(succeeded_runs / total_runs * 100, 2) if total_runs else 0.0
    quarantine_rate = (
        round(quarantined_rows / total_input_rows * 100, 2) if total_input_rows else 0.0
    )

    manifest_status = [
        {"status": row[0], "files": row[1], "size_bytes": row[2]}
        for row in manifest_rows
    ]
    total_files = sum(row[1] for row in manifest_rows)
    failed_files = sum(row[1] for row in manifest_rows if row[0] == "failed")

    trends: dict[str, dict[str, int]] = defaultdict(
        lambda: {"runs": 0, "succeeded": 0, "failed": 0, "input_rows": 0}
    )
    triggers: dict[str, dict[str, int]] = defaultdict(
        lambda: {"runs": 0, "succeeded": 0, "failed": 0}
    )
    recent_runs = []
    for row in run_rows:
        day = _date_key(row[2])
        trends[day]["runs"] += 1
        trends[day][row[3]] += 1
        trends[day]["input_rows"] += row[4]

        trigger_type = row[10]
        triggers[trigger_type]["runs"] += 1
        triggers[trigger_type][row[3]] += 1

        if len(recent_runs) < recent_limit:
            recent_runs.append(
                {
                    "run_id": row[0],
                    "completed_at": serialize(row[2]),
                    "status": row[3],
                    "trigger_type": trigger_type,
                    "batch_date": serialize(row[9]),
                    "input_rows": row[4],
                    "accepted_rows": row[5],
                    "quarantined_rows": row[6],
                    "deduplicated_rows": row[7],
                    "duration_seconds": _duration_seconds(row[1], row[2]),
                    "error_message": row[8],
                }
            )

    daily_trends = [
        {"date": day, **metrics} for day, metrics in sorted(trends.items())
    ]
    trigger_breakdown = [
        {"trigger_type": trigger, **metrics}
        for trigger, metrics in sorted(triggers.items())
    ]
    quality_failures = [
        {
            "run_id": row[0],
            "check_name": row[1],
            "violations": row[2],
            "checked_at": serialize(row[3]),
            "trigger_type": row[4],
            "batch_date": serialize(row[5]),
        }
        for row in quality_rows
    ]

    alerts = []
    if run_rows and run_rows[0][3] == "failed":
        alerts.append("The latest pipeline run failed")
    if total_runs and success_rate < success_slo_percent:
        alerts.append(
            f"Run success rate is {success_rate:.2f}%, below the {success_slo_percent:.2f}% SLO"
        )
    if failed_files:
        alerts.append(f"{failed_files} landed file(s) are in failed state")
    if quality_failures:
        alerts.append(f"{len(quality_failures)} persisted quality check(s) have failed")

    if not total_runs:
        platform_status = "no_runs"
    elif alerts:
        platform_status = "degraded"
    else:
        platform_status = "healthy"

    return {
        "platform_status": platform_status,
        "success_slo_percent": success_slo_percent,
        "alerts": alerts,
        "overview": {
            "total_runs": total_runs,
            "succeeded_runs": succeeded_runs,
            "failed_runs": failed_runs,
            "success_rate_percent": success_rate,
            "total_input_rows": total_input_rows,
            "accepted_rows": accepted_rows,
            "quarantined_rows": quarantined_rows,
            "quarantine_rate_percent": quarantine_rate,
            "deduplicated_rows": deduplicated_rows,
            "total_files": total_files,
            "failed_files": failed_files,
        },
        "daily_trends": daily_trends,
        "trigger_breakdown": trigger_breakdown,
        "recent_runs": recent_runs,
        "manifest_status": manifest_status,
        "quality_failures": quality_failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report historical platform metrics as JSON.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATA_PLATFORM_DATABASE_URL", "sqlite:///warehouse.db"),
    )
    parser.add_argument("--recent-limit", type=int, default=50)
    parser.add_argument("--success-slo-percent", type=float, default=95.0)
    args = parser.parse_args()
    print(
        json.dumps(
            get_monitoring_snapshot(
                args.database_url,
                recent_limit=args.recent_limit,
                success_slo_percent=args.success_slo_percent,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
