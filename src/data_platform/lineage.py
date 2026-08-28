"""OpenLineage event construction and fail-open delivery."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

LOGGER = logging.getLogger(__name__)
PRODUCER = "https://github.com/kdgmax/production-data-platform"
DEFAULT_NAMESPACE = "production-data-platform"

ORDER_SCHEMA = (
    ("order_id", "string"),
    ("customer_id", "string"),
    ("order_ts", "timestamp"),
    ("status", "string"),
    ("amount_usd", "decimal(18,2)"),
    ("source_updated_at", "timestamp"),
)


def _enabled(value: str | None) -> bool:
    return value is not None and value.lower() in {"1", "true", "yes", "on"}


def _event_time() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _nominal_time(value: date | datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


@dataclass(frozen=True)
class LineageDataset:
    namespace: str
    name: str
    schema: tuple[tuple[str, str], ...] = ()


def source_dataset(uri: str | Path) -> LineageDataset:
    """Create a stable dataset identity from a local path or object URI."""
    raw_uri = str(uri)
    parsed = urlsplit(raw_uri)
    if parsed.scheme == "s3":
        return LineageDataset(
            namespace=f"s3://{parsed.netloc}",
            name=unquote(parsed.path).lstrip("/"),
            schema=ORDER_SCHEMA,
        )
    if parsed.scheme == "file":
        return LineageDataset(
            namespace="file",
            name=str(Path(unquote(parsed.path)).resolve()),
            schema=ORDER_SCHEMA,
        )
    if parsed.scheme:
        return LineageDataset(
            namespace=f"{parsed.scheme}://{parsed.netloc}",
            name=unquote(parsed.path).lstrip("/"),
            schema=ORDER_SCHEMA,
        )
    return LineageDataset(namespace="file", name=str(Path(raw_uri).resolve()), schema=ORDER_SCHEMA)


def database_namespace(database_url: str) -> str:
    """Return a database namespace without usernames, passwords, or query parameters."""
    parsed = urlsplit(database_url)
    if parsed.scheme == "sqlite":
        return f"sqlite://{parsed.path}"

    host = parsed.hostname or "localhost"
    port = f":{parsed.port}" if parsed.port else ""
    database_name = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{host}{port}{database_name}"


def warehouse_datasets(database_url: str) -> list[LineageDataset]:
    namespace = database_namespace(database_url)
    return [
        LineageDataset(namespace, "staging_orders", ORDER_SCHEMA),
        LineageDataset(namespace, "dim_customers"),
        LineageDataset(namespace, "fact_orders", ORDER_SCHEMA),
        LineageDataset(namespace, "quarantined_orders"),
        LineageDataset(namespace, "data_quality_results"),
        LineageDataset(namespace, "pipeline_runs"),
    ]


def spark_output_datasets(output_root: Path, batch_date: date) -> list[LineageDataset]:
    partition = f"batch_date={batch_date.isoformat()}"
    return [
        LineageDataset(
            "file",
            str((output_root / "accepted_orders" / partition).resolve()),
            ORDER_SCHEMA + (("batch_date", "date"),),
        ),
        LineageDataset(
            "file",
            str((output_root / "quarantined_orders" / partition).resolve()),
        ),
    ]


class LineageEmitter:
    """Emit OpenLineage events while keeping metadata delivery off the data path."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        namespace: str = DEFAULT_NAMESPACE,
        strict: bool = False,
    ) -> None:
        self.client = client
        self.namespace = namespace
        self.strict = strict

    @classmethod
    def from_environment(cls) -> LineageEmitter:
        if not _enabled(os.getenv("DATA_PLATFORM_OPENLINEAGE_ENABLED")):
            return cls()
        try:
            from openlineage.client import OpenLineageClient
        except ImportError as error:
            raise RuntimeError(
                'OpenLineage is enabled; install it with pip install -e ".[lineage]"'
            ) from error
        return cls(
            OpenLineageClient(),
            namespace=os.getenv("DATA_PLATFORM_OPENLINEAGE_NAMESPACE", DEFAULT_NAMESPACE),
            strict=_enabled(os.getenv("DATA_PLATFORM_OPENLINEAGE_STRICT")),
        )

    def _emit(self, event: Any) -> None:
        if self.client is None:
            return
        try:
            self.client.emit(event)
        except Exception:
            LOGGER.warning("OpenLineage event delivery failed", exc_info=True)
            if self.strict:
                raise

    def emit_run_event(self, **event: Any) -> None:
        """Build and deliver one event without blocking processing unless strict mode is set."""
        if self.client is None:
            return
        try:
            self._emit_run_event(**event)
        except Exception:
            LOGGER.warning("OpenLineage event construction failed", exc_info=True)
            if self.strict:
                raise

    def _emit_run_event(
        self,
        *,
        state: str,
        run_id: str,
        job_name: str,
        inputs: list[LineageDataset],
        outputs: list[LineageDataset],
        nominal_start: date | datetime | None = None,
        output_row_counts: dict[str, int] | None = None,
        error: Exception | None = None,
        integration: str = "python",
    ) -> None:
        if self.client is None:
            return

        from openlineage.client.facet import (
            ErrorMessageRunFacet,
            JobTypeJobFacet,
            NominalTimeRunFacet,
            OutputStatisticsOutputDatasetFacet,
            SchemaDatasetFacet,
            SchemaField,
            SourceCodeLocationJobFacet,
        )
        from openlineage.client.run import (
            InputDataset,
            Job,
            OutputDataset,
            Run,
            RunEvent,
            RunState,
        )

        nominal = _nominal_time(nominal_start).isoformat().replace("+00:00", "Z")
        run_facets: dict[str, Any] = {
            "nominalTime": NominalTimeRunFacet(nominalStartTime=nominal),
        }
        if error is not None:
            run_facets["errorMessage"] = ErrorMessageRunFacet(
                message=str(error),
                programmingLanguage="python",
            )

        job_facets = {
            "jobType": JobTypeJobFacet(
                processingType="BATCH",
                integration=integration,
                jobType="PIPELINE",
            ),
            "sourceCodeLocation": SourceCodeLocationJobFacet(type="git", url=PRODUCER),
        }

        def schema_facets(dataset: LineageDataset) -> dict[str, Any]:
            if not dataset.schema:
                return {}
            return {
                "schema": SchemaDatasetFacet(
                    fields=[SchemaField(name=name, type=field_type) for name, field_type in dataset.schema]
                )
            }

        input_events = [
            InputDataset(item.namespace, item.name, facets=schema_facets(item)) for item in inputs
        ]
        output_events = []
        for item in outputs:
            output_facets: dict[str, Any] = {}
            if output_row_counts and item.name in output_row_counts:
                output_facets["outputStatistics"] = OutputStatisticsOutputDatasetFacet(
                    rowCount=output_row_counts[item.name]
                )
            output_events.append(
                OutputDataset(
                    item.namespace,
                    item.name,
                    facets=schema_facets(item),
                    outputFacets=output_facets,
                )
            )

        event = RunEvent(
            eventType=RunState[state],
            eventTime=_event_time(),
            run=Run(run_id, facets=run_facets),
            job=Job(self.namespace, job_name, facets=job_facets),
            producer=PRODUCER,
            inputs=input_events,
            outputs=output_events,
        )
        self._emit(event)


def lineage_job_name(trigger_type: str) -> str:
    if trigger_type == "airflow":
        return "orders.airflow_partition"
    if trigger_type == "ecs":
        return "orders.ecs_partition"
    return "orders.warehouse_load"


def lineage_integration(trigger_type: str) -> str:
    """Return the OpenLineage integration label for the execution runtime."""
    if trigger_type in {"airflow", "ecs"}:
        return trigger_type
    return "python"

