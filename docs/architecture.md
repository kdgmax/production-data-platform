# Architecture and engineering decisions

## Goal

This repository is a small reference implementation of the reliability patterns used in larger
batch platforms. It loads order events from CSV into a local analytical warehouse while preserving
bad records for investigation and making reruns safe.

## Data flow

```mermaid
flowchart TD
    A["Source CSV"] --> B["Schema and row validation"]
    B -->|valid| C["Idempotent staging upsert"]
    B -->|invalid| D["Quarantine table"]
    C --> E["Customer dimension"]
    C --> F["Order fact table"]
    D --> G["Run metrics"]
    E --> G
    F --> G
```

## Reliability properties

| Property | Implementation |
| --- | --- |
| Idempotency | `order_id` is the business key and a rerun does not duplicate facts. |
| Late updates | A record is updated only when `source_updated_at` is newer. |
| Batch deduplication | Multiple versions of one order are reduced to the newest version. |
| Data quality | Invalid amounts, statuses, identifiers, and timestamps are quarantined. |
| Atomicity | Staging, transformations, quarantine writes, and audit metrics share one transaction. |
| Reconciliation | Four SQL checks run after transformation and are stored for every batch. |
| Failure audit | Failed runs are persisted with their exception message after rollback. |
| Observability | Every execution emits JSON logs and writes counts and status to `pipeline_runs`. |
| Portability | The same pipeline contract runs against SQLite and PostgreSQL. |
| Schema evolution | Ordered SQL migrations are recorded in `schema_migrations`. |
| Concurrency control | A database-backed lock prevents overlapping pipeline writers. |
| Safe replay | Date partitions can be rerun without duplicating facts. |
| Retry control | Transient database and lock failures use bounded exponential backoff. |
| Reproducibility | Docker Compose starts PostgreSQL and runs the pipeline locally. |

## Warehouse model

- `staging_orders` stores the newest accepted source representation for every order.
- `dim_customers` assigns a surrogate key and tracks the first and last observed order time.
- `fact_orders` stores order-level measures and joins to the customer dimension.
- `quarantined_orders` preserves the raw record and all validation failures.
- `pipeline_runs` provides an audit trail for every execution.
- `data_quality_results` stores each post-transformation reconciliation result.
- `pipeline_locks` stores expiring ownership records for active writers.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
run-data-pipeline --input data/sample_orders.csv --database-url sqlite:///warehouse.db
pytest
```

The sample includes one negative amount to demonstrate quarantine behavior.

## Storage modes

SQLite keeps the learning path runnable in minutes. PostgreSQL demonstrates the same reliability
contract against a production-grade database, with dialect-specific DDL and transformations kept
in version-controlled SQL. GitHub Actions runs the test suite against PostgreSQL on every pull
request.

Run the complete PostgreSQL stack with:

```bash
docker compose up --build
```

Inspect the latest run with:

```bash
data-platform-health --database-url sqlite:///warehouse.db
```

## Backfills and orchestration

Historical partitions are replayed through the same validation, transformation, reconciliation,
and audit path as a manual run:

```bash
data-platform-backfill \
  --start-date 2026-08-25 \
  --end-date 2026-08-27 \
  --source-template 'data/partitions/date={date}/orders.csv' \
  --database-url sqlite:///warehouse.db
```

Each run stores `batch_date` and `trigger_type`. A replay is safe because staging and fact tables
use business-key upserts with source-version comparisons. Locks expire automatically so a crashed
worker cannot block the pipeline permanently.

## Planned milestones

1. Add an object-storage landing zone and file manifest.
2. Add a Spark implementation for partitioned, higher-volume data.
