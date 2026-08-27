"""Minimal structured logging for pipeline operations."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

LOG_FIELDS = (
    "event",
    "run_id",
    "input_rows",
    "accepted_rows",
    "quarantined_rows",
    "deduplicated_rows",
    "quality_checks_passed",
    "error_type",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str | int] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in LOG_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, sort_keys=True)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)

