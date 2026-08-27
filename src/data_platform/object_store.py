"""Materialize local or S3-compatible objects for pipeline processing."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import boto3


@dataclass(frozen=True)
class MaterializedObject:
    uri: str
    path: Path
    etag: str | None


@contextmanager
def materialize_object(source_uri: str) -> Iterator[MaterializedObject]:
    if not source_uri.startswith("s3://"):
        path = Path(source_uri.removeprefix("file://")).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"source object does not exist: {source_uri}")
        yield MaterializedObject(uri=source_uri, path=path, etag=None)
        return

    parsed = urlparse(source_uri)
    if not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError("S3 URI must include a bucket and object key")

    client = boto3.client(
        "s3",
        endpoint_url=os.getenv("DATA_PLATFORM_S3_ENDPOINT_URL"),
    )
    response = client.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
    etag = response.get("ETag", "").strip('"') or None
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(prefix="data-platform-", suffix=".csv", delete=False) as tmp:
            temporary_path = Path(tmp.name)
            for chunk in response["Body"].iter_chunks(chunk_size=1024 * 1024):
                tmp.write(chunk)
        yield MaterializedObject(uri=source_uri, path=temporary_path, etag=etag)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

