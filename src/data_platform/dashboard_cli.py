"""Command-line launcher for the Streamlit operations dashboard."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the platform operations dashboard.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATA_PLATFORM_DATABASE_URL", "sqlite:///warehouse.db"),
    )
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()

    try:
        import streamlit  # noqa: F401
    except ImportError as error:
        raise RuntimeError(
            'Dashboard support is optional; install it with pip install -e ".[dashboard]"'
        ) from error

    os.environ["DATA_PLATFORM_DATABASE_URL"] = args.database_url
    dashboard_path = Path(__file__).with_name("dashboard.py")
    streamlit_executable = Path(sys.executable).with_name("streamlit")
    os.execv(
        streamlit_executable,
        [
            str(streamlit_executable),
            "run",
            str(dashboard_path),
            "--server.port",
            str(args.port),
            "--server.headless",
            "true",
            "--server.address",
            "127.0.0.1",
            "--browser.gatherUsageStats",
            "false",
        ],
    )


if __name__ == "__main__":
    main()
