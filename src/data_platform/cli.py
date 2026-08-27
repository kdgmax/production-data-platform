"""Command-line entry point for the data pipeline."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .observability import configure_logging
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load an orders CSV into the local warehouse.")
    parser.add_argument("--input", type=Path, required=True, help="Path to the source CSV file.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATA_PLATFORM_DATABASE_URL", "sqlite:///warehouse.db"),
        help="SQLite or PostgreSQL URL. Defaults to sqlite:///warehouse.db.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Structured log level. Defaults to INFO.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    configure_logging(args.log_level)
    metrics = run_pipeline(input_path=args.input, database_url=args.database_url)
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
