"""Post-transformation reconciliation checks."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .sql_loader import read_sql


@dataclass(frozen=True)
class QualityResult:
    check_name: str
    violation_count: int

    @property
    def passed(self) -> bool:
        return self.violation_count == 0


class DataQualityError(RuntimeError):
    """Raised when a reconciliation check detects a warehouse inconsistency."""


def run_reconciliation_checks(connection: sqlite3.Connection) -> list[QualityResult]:
    rows = connection.execute(read_sql("reconciliation.sql")).fetchall()
    return [QualityResult(check_name=row[0], violation_count=row[1]) for row in rows]


def assert_quality(results: list[QualityResult]) -> None:
    failures = [result for result in results if not result.passed]
    if failures:
        summary = ", ".join(
            f"{result.check_name}={result.violation_count}" for result in failures
        )
        raise DataQualityError(f"reconciliation checks failed: {summary}")

