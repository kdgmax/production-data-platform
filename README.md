# Production Data Platform

[![CI](https://github.com/kdgmax/production-data-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/kdgmax/production-data-platform/actions/workflows/ci.yml)

A production-minded batch data platform built with Python, SQL, PostgreSQL, SQLite, Docker, and GitHub Actions. It demonstrates how to ingest imperfect source data, preserve invalid records, model analytical tables, verify data quality, and make every pipeline run auditable.

## Why this project exists

Moving data is the easy part. A reliable platform must also handle duplicate events, late updates, invalid records, schema changes, partial failures, and operational investigation.

This repository implements those concerns in a small system that can be run locally and understood end to end.

## What it demonstrates

| Capability | Implementation |
| --- | --- |
| Incremental ingestion | Orders are upserted using a stable business key and `source_updated_at`. |
| Idempotency | Rerunning the same batch does not duplicate warehouse records. |
| Late-arriving updates | A record changes only when the source version is newer. |
| Data quality | Invalid rows are quarantined and four SQL reconciliation checks validate the marts. |
| Analytical modeling | Source orders become a customer dimension and order fact table. |
| Atomicity | Failed transformations or quality checks roll back the complete batch. |
| Schema evolution | Ordered SQL migrations are tracked in `schema_migrations`. |
| Backfills | Date-partitioned files can be replayed through the same production path. |
| Concurrency safety | Expiring database locks prevent overlapping writers. |
| Retry behavior | Transient failures use bounded exponential backoff. |
| Observability | JSON logs, run metrics, error messages, and quality results support investigation. |
| Portability | The same pipeline runs against SQLite and PostgreSQL. |
| Delivery controls | Pull requests run linting, unit tests, and a PostgreSQL integration test. |

## Architecture

```mermaid
flowchart TD
    A["CSV source"] --> B["Validation and deduplication"]
    B -->|valid| C["Incremental staging"]
    B -->|invalid| D["Quarantine"]
    C --> E["Dimension and fact models"]
    E --> F["SQL reconciliation"]
    D --> G["Run audit and JSON logs"]
    F --> G
```

Read the detailed [architecture and engineering decisions](docs/architecture.md).

## Quick start with SQLite

Requirements: Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"

run-data-pipeline \
  --input data/sample_orders.csv \
  --database-url sqlite:///warehouse.db
```

The sample input contains three valid orders and one negative amount. The pipeline loads the valid records and quarantines the invalid one instead of silently dropping it.

Example result:

```json
{
  "accepted_rows": 3,
  "deduplicated_rows": 0,
  "input_rows": 4,
  "quality_checks_passed": 4,
  "quarantined_rows": 1,
  "status": "succeeded"
}
```

## Run with PostgreSQL

Start PostgreSQL and run the pipeline through Docker Compose:

```bash
docker compose up --build
```

The application waits for PostgreSQL to become healthy, applies any pending migrations, and loads the sample batch.

You can also point the CLI at an existing PostgreSQL database:

```bash
run-data-pipeline \
  --input data/sample_orders.csv \
  --database-url postgresql://user:password@localhost:5432/data_platform
```

## Check pipeline health

```bash
data-platform-health --database-url sqlite:///warehouse.db
```

The health command returns the latest run status, ingestion metrics, error information, and every reconciliation result.

## Run a historical backfill

```bash
data-platform-backfill \
  --start-date 2026-08-25 \
  --end-date 2026-08-27 \
  --source-template 'data/partitions/date={date}/orders.csv' \
  --database-url sqlite:///warehouse.db
```

Every partition is recorded with its batch date and trigger type. Replaying the same range does not
duplicate facts, and `--continue-on-error` allows independent dates to proceed when one partition
is missing or invalid.

## Warehouse model

- `staging_orders`: newest accepted source version for each order
- `dim_customers`: surrogate customer key with first and last observed timestamps
- `fact_orders`: order measures joined to the customer dimension
- `quarantined_orders`: raw invalid records with validation reasons
- `pipeline_runs`: status and row-level metrics for every execution
- `data_quality_results`: reconciliation results associated with a pipeline run
- `schema_migrations`: ordered migration history for the selected database
- `pipeline_locks`: expiring ownership records that prevent overlapping writers

## Repository structure

```text
src/data_platform/
  pipeline.py          ingestion and transactional orchestration
  database.py          SQLite and PostgreSQL adapter
  migrations.py        ordered schema migration runner
  quality.py           reconciliation enforcement
  health.py            latest-run operational summary
  backfill.py          date-range replay and retry orchestration
  locking.py           database-backed concurrency control
  observability.py     structured JSON logging
  sql/                 dialect-specific migrations and models
tests/                 unit, failure-path, health, and integration tests
data/                  synthetic source data
.github/workflows/     CI configuration
```

## Test and validate

```bash
pytest
ruff check .
```

GitHub Actions also starts a PostgreSQL service and executes the full integration path on every pull request.

## Engineering decisions

- The first implementation stays intentionally small so transaction boundaries and SQL behavior remain visible.
- Synthetic order data avoids exposing employer, customer, or proprietary information.
- SQLite supports a five-minute local start, while PostgreSQL proves the design against a production-grade database.
- Dialect-specific SQL is explicit rather than hidden behind an ORM, making differences such as `MIN` versus `LEAST` reviewable.
- Quality results are stored as data, not only emitted as logs, so historical runs can be audited.

## Roadmap

- Land source files in object storage before warehouse loading
- Add partitioned Spark processing for higher-volume batches
- Publish run-health metrics to an observability dashboard
