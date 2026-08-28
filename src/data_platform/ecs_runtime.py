"""One-off ECS entry point with database credentials assembled at runtime."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from urllib.parse import quote

from .landing import process_source_file
from .observability import configure_logging

DATABASE_ENVIRONMENT_KEYS = (
    "DATA_PLATFORM_DB_HOST",
    "DATA_PLATFORM_DB_PORT",
    "DATA_PLATFORM_DB_NAME",
    "DATA_PLATFORM_DB_USERNAME",
    "DATA_PLATFORM_DB_PASSWORD",
)


def database_url_from_environment(environment: dict[str, str] | None = None) -> str:
    """Build a PostgreSQL URL without ever logging the injected secret values."""
    environment = environment or os.environ
    missing = [key for key in DATABASE_ENVIRONMENT_KEYS if not environment.get(key)]
    if missing:
        raise RuntimeError(f"missing required database environment variables: {', '.join(missing)}")

    username = quote(environment["DATA_PLATFORM_DB_USERNAME"], safe="")
    password = quote(environment["DATA_PLATFORM_DB_PASSWORD"], safe="")
    host = environment["DATA_PLATFORM_DB_HOST"]
    port = environment["DATA_PLATFORM_DB_PORT"]
    database = quote(environment["DATA_PLATFORM_DB_NAME"], safe="")
    return f"postgresql://{username}:{password}@{host}:{port}/{database}?sslmode=require"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one private ECS order partition.")
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--batch-date", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    args = parser.parse_args()
    configure_logging(args.log_level)
    result = process_source_file(
        source_uri=args.source_uri,
        database_url=database_url_from_environment(),
        batch_date=args.batch_date,
        trigger_type="ecs",
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

