"""Small database adapter for SQLite and PostgreSQL."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Self

sqlite3.register_adapter(datetime, lambda value: value.isoformat())
sqlite3.register_adapter(date, lambda value: value.isoformat())


class UnsupportedDatabaseError(ValueError):
    """Raised when a database URL uses an unsupported scheme."""


class Database:
    def __init__(self, connection: Any, dialect: str) -> None:
        self.connection = connection
        self.dialect = dialect

    @classmethod
    def connect(cls, database_url: str) -> Self:
        if database_url.startswith("sqlite:///"):
            raw_path = database_url.removeprefix("sqlite:///")
            if raw_path != ":memory:":
                Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(raw_path)
            connection.execute("PRAGMA foreign_keys = ON")
            return cls(connection, "sqlite")

        if database_url.startswith(("postgresql://", "postgres://")):
            import psycopg

            return cls(psycopg.connect(database_url, autocommit=True), "postgresql")

        raise UnsupportedDatabaseError(
            "database URL must start with sqlite:/// or postgresql://"
        )

    def _prepare(self, query: str) -> str:
        if self.dialect == "postgresql":
            return query.replace("?", "%s")
        return query

    def execute(self, query: str, parameters: Sequence[Any] = ()):
        return self.connection.execute(self._prepare(query), parameters)

    def executemany(self, query: str, rows: Sequence[Sequence[Any]]) -> None:
        prepared = self._prepare(query)
        if self.dialect == "sqlite":
            self.connection.executemany(prepared, rows)
            return

        with self.connection.cursor() as cursor:
            cursor.executemany(prepared, rows)

    def execute_script(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self.dialect == "sqlite":
            with self.connection:
                yield
            return

        with self.connection.transaction():
            yield

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def sqlite_url(database_path: Path) -> str:
    return f"sqlite:///{database_path.resolve()}"
