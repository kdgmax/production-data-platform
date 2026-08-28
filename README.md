# Production Data Platform

[![CI](https://github.com/kdgmax/production-data-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/kdgmax/production-data-platform/actions/workflows/ci.yml)

A production-minded batch data platform built with Python, SQL, Spark, S3, PostgreSQL, SQLite,
Parquet, Docker, and GitHub Actions. It demonstrates both transactional warehouse loading and
partitioned scale-out processing while keeping duplicate prevention, quarantine, quality, and
lineage consistent across engines.

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
| Object storage | Local and S3-compatible objects share one landing interface. |
| Exactly-once files | SHA-256 manifest claims prevent duplicate content from being processed twice. |
| File lineage | Every successful object records its URI, checksum, size, ETag, batch date, and run ID. |
| Scale-out processing | Spark applies schema enforcement, deterministic deduplication, and quarantine rules. |
| Partitioned lake output | Accepted and rejected rows are written as batch-date-partitioned Parquet datasets. |
| Operational dashboard | Streamlit visualizes SLOs, throughput, quarantine, quality, and file health. |
| Machine-readable monitoring | The same portable metrics contract is available as JSON for automation. |
| Scheduled orchestration | Airflow 3 schedules daily partitions with catchup, retries, dependencies, and SLO gates. |
| OpenLineage | Warehouse, Spark, and Airflow-triggered runs emit interoperable job and dataset lineage. |
| Cloud infrastructure | Terraform provisions private networking, encrypted S3 and RDS, scoped IAM, and alarms. |
| On-demand cloud runtime | Private ECS Fargate tasks deploy through approval-protected GitHub OIDC. |
| Portability | The same pipeline runs against SQLite and PostgreSQL. |
| Delivery controls | Pull requests run linting, Terraform validation, Spark tests, and a PostgreSQL integration test. |

## Architecture

```mermaid
flowchart TD
    A["Local or S3 object"] --> B["Checksum and manifest claim"]
    B -->|known| C["Skip duplicate content"]
    B -->|new| D{"Processing engine"}
    D -->|Python and SQL| E["Warehouse models"]
    D -->|Spark| F["Partitioned Parquet"]
    E --> G["Quality and lineage"]
    F --> G
    G --> H["OpenLineage events"]
    G --> I["Operations dashboard"]
    I --> J["Airflow SLO gate"]
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

## Land a local or S3 object

```bash
data-platform-land \
  --source-uri s3://my-data-bucket/orders/date=2026-08-27/orders.csv \
  --batch-date 2026-08-27 \
  --database-url postgresql://user:password@localhost:5432/data_platform
```

The landing command materializes the object, calculates its SHA-256 checksum, atomically claims
the checksum in `file_manifest`, and runs the normal pipeline. Re-uploading identical bytes under
a different key is skipped and linked to the original successful run.

Standard AWS credentials are supported automatically. An S3-compatible service can be selected
with `DATA_PLATFORM_S3_ENDPOINT_URL`.

## Process a partition with Spark

Requirements: Java 17 and the optional Spark dependency.

```bash
python -m pip install -e ".[dev,spark]"

data-platform-spark \
  --source-uri s3://my-data-bucket/orders/date=2026-08-27/orders.csv \
  --batch-date 2026-08-27 \
  --output-root ./lake \
  --database-url postgresql://user:password@localhost:5432/data_platform
```

The Spark path uses an explicit string input schema, validates identifiers, statuses, amounts,
and timezone-aware timestamps, then deterministically keeps the newest version of each order.
Valid and quarantined rows are written separately as Parquet under `batch_date` partitions. The
same checksum manifest, database lock, run audit, and persisted quality results remain in effect.

Local mode defaults to `local[2]`. A cluster master can be supplied with `--master` without
changing the transformation contract.

## Monitor platform operations

Install the optional dashboard dependency and launch Streamlit:

```bash
python -m pip install -e ".[dashboard]"

data-platform-dashboard \
  --database-url sqlite:///warehouse.db \
  --port 8501
```

The dashboard shows eight operational KPIs, daily success and failure trends, input volume,
execution-path breakdowns, recent run drill-downs, persisted quality failures, and file-manifest
status. A configurable success-rate SLO changes the platform state to `degraded` when reliability
falls below the target.

The same snapshot is available as JSON for scripts, alerts, or external monitoring systems:

```bash
data-platform-observe \
  --database-url sqlite:///warehouse.db \
  --success-slo-percent 95
```

## Orchestrate daily partitions with Airflow

Start the local Airflow 3 environment and its PostgreSQL metadata database:

```bash
docker compose -f docker-compose.airflow.yml up --build
```

Open `http://localhost:8080`. Airflow standalone prints the generated local administrator
credentials in the container logs. The `orders_daily` DAG runs at 06:00 UTC and processes the
partition associated with each logical date.

The DAG demonstrates:

- TaskFlow authoring through Airflow 3's stable `airflow.sdk` interface
- `resolve_partition` to `process_partition` to `evaluate_platform_slo` dependencies
- Three processing retries with exponential backoff from 1 to 15 minutes
- `catchup=True` for date-range backfills using the same production path
- `max_active_runs=1` plus database locks for layered concurrency protection
- XCom-based result passing and a final reliability SLO gate

Runtime settings are supplied through environment variables:

| Variable | Purpose |
| --- | --- |
| `DATA_PLATFORM_SOURCE_TEMPLATE` | Local or S3 URI containing a `{date}` placeholder. |
| `DATA_PLATFORM_DATABASE_URL` | SQLite or PostgreSQL target for pipeline state and models. |
| `DATA_PLATFORM_SUCCESS_SLO` | Minimum historical run-success percentage, default `95`. |

The Compose file uses PostgreSQL for Airflow metadata and a separate `data_platform` database for
pipeline state. For production, credentials should come from Airflow Connections or an external
secrets backend rather than inline development values.

## Trace datasets with OpenLineage

Install the optional lineage client and enable file-based events locally:

```bash
python -m pip install -e ".[lineage]"
cp openlineage.yml.example openlineage.yml
export DATA_PLATFORM_OPENLINEAGE_ENABLED=true
export OPENLINEAGE_CONFIG="$PWD/openlineage.yml"
run-data-pipeline --input data/sample_orders.csv --database-url sqlite:///warehouse.db
```

`lineage-events.jsonl` will contain a `START` event followed by `COMPLETE` or `FAIL`. Every event
uses the same run UUID stored in `pipeline_runs` and describes the job, source dataset, output
datasets, schema, nominal batch time, code location, and available output row counts.

The integration distinguishes `orders.warehouse_load`, `orders.spark_transform`,
`orders.airflow_partition`, and `orders.ecs_partition`. S3 identities remain stable after local materialization, while database
namespaces exclude usernames, passwords, and query parameters. Delivery is fail open by default so
a lineage backend outage does not stop data processing. Set `DATA_PLATFORM_OPENLINEAGE_STRICT=true`
only when lineage delivery must be part of pipeline success.

The Airflow Compose environment enables file transport automatically. Inspect emitted events with:

```bash
docker compose -f docker-compose.airflow.yml exec airflow \
  tail -n 2 /opt/airflow/logs/openlineage-events.jsonl
```

To use Marquez or another compatible backend, replace the file transport in `openlineage.yml` with
the backend's HTTP transport configuration.

## Provision AWS infrastructure with Terraform

The `infrastructure` module defines a deliberately small AWS foundation for the platform:

- An isolated VPC with two private subnets and no internet gateway or NAT gateway
- KMS-encrypted landing and processed S3 buckets with versioning, retention, and public access blocked
- A private encrypted PostgreSQL RDS instance with an RDS-managed Secrets Manager password
- Separate resource-scoped ECS application and execution roles
- An S3 gateway endpoint, optional private service endpoints, and RDS CloudWatch alarms

Terraform validates in CI, but CI never runs `plan` or `apply`. This keeps cloud credentials and
resource creation outside pull-request automation. To inspect the module locally:

```bash
cp infrastructure/terraform.tfvars.example infrastructure/terraform.tfvars
terraform -chdir=infrastructure init
terraform -chdir=infrastructure fmt -check
terraform -chdir=infrastructure validate
terraform -chdir=infrastructure plan
```

Pipeline compute is opt-in and disabled by default. The module outputs private subnet IDs, bucket
names, database connectivity, and ECS deployment identifiers without opening the data layer to the
public internet. See the [infrastructure guide](infrastructure/README.md) for deployment, state,
security, and cost notes.

## Run an approved partition on ECS

The optional ECS module turns the AWS foundation into an executable platform without creating an
always-on service. When `enable_ecs_runtime = true`, Terraform adds:

- A KMS-encrypted, immutable, scan-on-push ECR repository
- An ECS cluster and 0.25-vCPU, 512-MiB Fargate task definition
- A non-root, read-only application container with a dedicated writable scratch volume
- A no-ingress runtime security group with explicit S3, database, DNS, and endpoint egress
- ECR, Secrets Manager, KMS, and CloudWatch Logs private endpoints
- Separate task, task-execution, and GitHub deployment IAM roles
- A GitHub OIDC trust policy restricted to this repository's `production` environment

The manual `Deploy and run ECS pipeline` workflow requires environment approval, obtains short-lived
AWS credentials, pushes an image tagged with the commit SHA, registers a task revision, runs it in
private subnets without a public IP, waits for completion, and checks the container exit code.

Terraform keeps the runtime disabled by default because private interface endpoints have recurring
cost. No AWS deployment or apply occurs in normal CI. Follow the complete
[ECS deployment runbook](docs/ecs-deployment.md) before enabling it.

## Warehouse model

- `staging_orders`: newest accepted source version for each order
- `dim_customers`: surrogate customer key with first and last observed timestamps
- `fact_orders`: order measures joined to the customer dimension
- `quarantined_orders`: raw invalid records with validation reasons
- `pipeline_runs`: status and row-level metrics for every execution
- `data_quality_results`: reconciliation results associated with a pipeline run
- `schema_migrations`: ordered migration history for the selected database
- `pipeline_locks`: expiring ownership records that prevent overlapping writers
- `file_manifest`: object-level checksum, lineage, status, and processing ownership

## Repository structure

```text
src/data_platform/
  pipeline.py          ingestion and transactional orchestration
  database.py          SQLite and PostgreSQL adapter
  migrations.py        ordered schema migration runner
  quality.py           reconciliation enforcement
  health.py            latest-run operational summary
  backfill.py          date-range replay and retry orchestration
  landing.py           checksum claims and exactly-once file processing
  object_store.py      local and S3-compatible object materialization
  spark_pipeline.py    partitioned Spark validation and Parquet processing
  monitoring.py        portable historical metrics and SLO evaluation
  dashboard.py         Streamlit operations dashboard
  dashboard_cli.py     dashboard process launcher
  orchestration.py     scheduled partition runtime and SLO gate
  locking.py           database-backed concurrency control
  observability.py     structured JSON logging
  lineage.py           OpenLineage jobs, datasets, facets, and fail-open delivery
  ecs_runtime.py       secret-safe one-off Fargate entry point
  sql/                 dialect-specific migrations and models
tests/                 unit, failure-path, health, and integration tests
data/                  synthetic source data
.github/workflows/     CI configuration
dags/                  Airflow 3 DAG definitions
infrastructure/        secure AWS foundation expressed as Terraform
openlineage.yml.example local OpenLineage file-transport configuration
Dockerfile.ecs         non-root image for one-off Fargate tasks
```

## Test and validate

```bash
pytest
ruff check .
terraform fmt -check -recursive infrastructure
terraform -chdir=infrastructure init -backend=false
terraform -chdir=infrastructure validate
```

GitHub Actions installs Airflow, Spark, and Streamlit, validates Terraform and the Airflow Compose
file, starts a PostgreSQL service, executes both processing engines, parses the DAG graph, and
renders the dashboard through Streamlit's application test harness on every pull request.

## Engineering decisions

- The first implementation stays intentionally small so transaction boundaries and SQL behavior remain visible.
- Synthetic order data avoids exposing employer, customer, or proprietary information.
- SQLite supports a five-minute local start, while PostgreSQL proves the design against a production-grade database.
- Dialect-specific SQL is explicit rather than hidden behind an ORM, making differences such as `MIN` versus `LEAST` reviewable.
- Quality results are stored as data, not only emitted as logs, so historical runs can be audited.
- Spark is an optional dependency so the lightweight Python and SQL learning path remains fast.
- The Spark path writes Parquet lake datasets while the transactional path owns warehouse models.
- Dashboard metrics live in a UI-independent query layer so they can also power alerts and APIs.
- Airflow DAG code stays thin while orchestration runtime functions remain directly unit-testable.
- Catchup reuses the same exactly-once landing path instead of creating a separate backfill loader.
- OpenLineage run IDs match the warehouse audit IDs so metadata can be reconciled with operations.
- Lineage delivery is fail open by default, with strict mode available for governed environments.
- Terraform provides the shared data layer while compute remains a separate scaling decision.
- Private networking avoids recurring NAT cost and prevents accidental public database exposure.
- The ECS runtime is opt-in, one task per partition, and never assigns a public IP.
- GitHub OIDC replaces stored AWS access keys and trusts only an approval-protected environment.


