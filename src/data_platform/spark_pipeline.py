"""Partitioned Spark pipeline with validation, quarantine, and manifest lineage."""

from __future__ import annotations

import argparse
import csv
import json
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from .database import Database
from .landing import claim_file, finish_file, identify_file
from .locking import acquire_lock, release_lock
from .migrations import apply_migrations
from .object_store import materialize_object
from .observability import configure_logging
from .pipeline import REQUIRED_COLUMNS, store_quality_results, store_run, utc_now
from .quality import QualityResult, assert_quality

OUTPUT_COLUMNS = [
    "order_id",
    "customer_id",
    "order_ts",
    "status",
    "amount_usd",
    "source_updated_at",
]


def require_pyspark():
    try:
        from pyspark.sql import SparkSession
    except ImportError as error:
        raise RuntimeError(
            'Spark support is optional; install it with pip install -e ".[spark]"'
        ) from error
    return SparkSession


def validate_header(input_path: Path) -> None:
    with input_path.open(newline="", encoding="utf-8") as source:
        header = next(csv.reader(source), [])
    missing_columns = REQUIRED_COLUMNS - set(header)
    if missing_columns:
        raise ValueError(f"input is missing required columns: {sorted(missing_columns)}")


def build_spark_session(*, master: str, app_name: str):
    SparkSession = require_pyspark()
    return (
        SparkSession.builder.master(master)
        .appName(app_name)
        .config("spark.ui.enabled", "false")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .getOrCreate()
    )


def transform_orders(spark, input_path: Path, *, run_id: str, batch_date: date):
    from pyspark.sql import Window
    from pyspark.sql import functions as F
    from pyspark.sql.types import StringType, StructField, StructType

    schema = StructType([StructField(column, StringType(), True) for column in OUTPUT_COLUMNS])
    source = spark.read.option("header", True).schema(schema).csv(str(input_path))

    timezone_pattern = r"(Z|[+-][0-9]{2}:[0-9]{2})$"
    normalized = (
        source.withColumn("order_id_clean", F.trim(F.col("order_id")))
        .withColumn("customer_id_clean", F.trim(F.col("customer_id")))
        .withColumn("status_clean", F.lower(F.trim(F.col("status"))))
        .withColumn("amount_clean", F.col("amount_usd").cast("decimal(18,2)"))
        .withColumn("order_ts_clean", F.to_timestamp("order_ts"))
        .withColumn("source_updated_at_clean", F.to_timestamp("source_updated_at"))
    )

    error_reason = F.concat_ws(
        "; ",
        F.when(
            F.col("order_id_clean").isNull() | (F.length("order_id_clean") == 0),
            "order_id is required",
        ),
        F.when(
            F.col("customer_id_clean").isNull() | (F.length("customer_id_clean") == 0),
            "customer_id is required",
        ),
        F.when(
            F.col("status_clean").isNull()
            | ~F.col("status_clean").isin("pending", "completed", "cancelled"),
            "status is invalid",
        ),
        F.when(F.col("amount_clean").isNull(), "amount_usd must be numeric"),
        F.when(F.col("amount_clean") < 0, "amount_usd must be non-negative"),
        F.when(
            F.col("order_ts_clean").isNull()
            | ~F.col("order_ts").rlike(timezone_pattern),
            "order_ts must be an ISO-8601 timestamp with a timezone",
        ),
        F.when(
            F.col("source_updated_at_clean").isNull()
            | ~F.col("source_updated_at").rlike(timezone_pattern),
            "source_updated_at must be an ISO-8601 timestamp with a timezone",
        ),
    )
    validated = normalized.withColumn("error_reason", error_reason).cache()

    quarantined = validated.where(F.length("error_reason") > 0).select(
        F.lit(run_id).alias("run_id"),
        F.to_json(F.struct(*[F.col(column) for column in OUTPUT_COLUMNS])).alias("raw_payload"),
        "error_reason",
        F.current_timestamp().alias("quarantined_at"),
        F.lit(batch_date.isoformat()).alias("batch_date"),
    )

    valid = validated.where(F.length("error_reason") == 0).select(
        F.col("order_id_clean").alias("order_id"),
        F.col("customer_id_clean").alias("customer_id"),
        F.col("order_ts_clean").alias("order_ts"),
        F.col("status_clean").alias("status"),
        F.col("amount_clean").alias("amount_usd"),
        F.col("source_updated_at_clean").alias("source_updated_at"),
    )
    tie_breaker = F.sha2(
        F.concat_ws("||", *[F.coalesce(F.col(column).cast("string"), F.lit("")) for column in OUTPUT_COLUMNS]),
        256,
    )
    window = Window.partitionBy("order_id").orderBy(
        F.col("source_updated_at").desc(), tie_breaker.desc()
    )
    accepted = (
        valid.withColumn("row_number", F.row_number().over(window))
        .where(F.col("row_number") == 1)
        .drop("row_number")
        .withColumn("batch_date", F.lit(batch_date.isoformat()))
    )
    return validated, valid, accepted, quarantined


def spark_quality_results(accepted) -> list[QualityResult]:
    from pyspark.sql import functions as F

    checks = [
        QualityResult(
            "spark_order_id_unique",
            accepted.groupBy("order_id").count().where(F.col("count") > 1).count(),
        ),
        QualityResult(
            "spark_customer_present",
            accepted.where(F.col("customer_id").isNull() | (F.length("customer_id") == 0)).count(),
        ),
        QualityResult(
            "spark_amount_non_negative",
            accepted.where(F.col("amount_usd").isNull() | (F.col("amount_usd") < 0)).count(),
        ),
        QualityResult(
            "spark_status_valid",
            accepted.where(~F.col("status").isin("pending", "completed", "cancelled")).count(),
        ),
    ]
    assert_quality(checks)
    return checks


def run_spark_pipeline(
    input_path: Path,
    *,
    output_root: Path,
    database_url: str,
    batch_date: date,
    master: str = "local[2]",
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    started_at = utc_now()
    metrics = {
        "input_rows": 0,
        "accepted_rows": 0,
        "quarantined_rows": 0,
        "deduplicated_rows": 0,
    }
    spark = None

    with Database.connect(database_url) as database:
        apply_migrations(database)
        acquire_lock(
            database,
            lock_name="spark_orders_pipeline",
            owner_run_id=run_id,
            ttl_seconds=3600,
        )
        try:
            validate_header(input_path)
            spark = build_spark_session(master=master, app_name=f"orders-{run_id}")
            validated, valid, accepted, quarantined = transform_orders(
                spark,
                input_path,
                run_id=run_id,
                batch_date=batch_date,
            )

            metrics["input_rows"] = validated.count()
            valid_rows = valid.count()
            metrics["accepted_rows"] = accepted.count()
            metrics["quarantined_rows"] = quarantined.count()
            metrics["deduplicated_rows"] = valid_rows - metrics["accepted_rows"]
            quality_results = spark_quality_results(accepted)

            accepted.write.mode("overwrite").partitionBy("batch_date").parquet(
                str(output_root / "accepted_orders")
            )
            quarantined.write.mode("overwrite").partitionBy("batch_date").parquet(
                str(output_root / "quarantined_orders")
            )

            with database.transaction():
                store_quality_results(database, run_id, quality_results)
                store_run(
                    database,
                    run_id=run_id,
                    started_at=started_at,
                    status="succeeded",
                    batch_date=batch_date,
                    trigger_type="spark",
                    **metrics,
                )
        except Exception as error:
            with database.transaction():
                store_run(
                    database,
                    run_id=run_id,
                    started_at=started_at,
                    status="failed",
                    batch_date=batch_date,
                    trigger_type="spark",
                    error_message=str(error),
                    **metrics,
                )
            raise
        finally:
            if spark is not None:
                spark.stop()
            release_lock(
                database,
                lock_name="spark_orders_pipeline",
                owner_run_id=run_id,
            )

    return {
        "run_id": run_id,
        "status": "succeeded",
        "batch_date": batch_date.isoformat(),
        "trigger_type": "spark",
        "quality_checks_passed": len(quality_results),
        "output_root": str(output_root),
        **metrics,
    }


def process_spark_source_file(
    *,
    source_uri: str,
    output_root: Path,
    database_url: str,
    batch_date: date,
    master: str = "local[2]",
) -> dict[str, Any]:
    with materialize_object(source_uri) as materialized:
        identity = identify_file(materialized.path)
        with Database.connect(database_url) as database:
            apply_migrations(database)
            claim_status, existing_run_id = claim_file(
                database,
                materialized=materialized,
                identity=identity,
                batch_date=batch_date,
            )

        if claim_status == "skipped":
            return {
                "status": "skipped",
                "reason": "checksum_already_succeeded",
                "source_uri": source_uri,
                "checksum_sha256": identity.checksum_sha256,
                "run_id": existing_run_id,
            }

        try:
            metrics = run_spark_pipeline(
                materialized.path,
                output_root=output_root,
                database_url=database_url,
                batch_date=batch_date,
                master=master,
            )
        except Exception as error:
            finish_file(
                database_url,
                checksum_sha256=identity.checksum_sha256,
                status="failed",
                error_message=str(error),
            )
            raise

        finish_file(
            database_url,
            checksum_sha256=identity.checksum_sha256,
            status="succeeded",
            run_id=str(metrics["run_id"]),
        )
        return {
            **metrics,
            "source_uri": source_uri,
            "checksum_sha256": identity.checksum_sha256,
            "size_bytes": identity.size_bytes,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Process a source object with partitioned Spark.")
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--batch-date", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATA_PLATFORM_DATABASE_URL", "sqlite:///warehouse.db"),
    )
    parser.add_argument("--master", default="local[2]")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    args = parser.parse_args()
    configure_logging(args.log_level)
    result = process_spark_source_file(
        source_uri=args.source_uri,
        output_root=args.output_root,
        database_url=args.database_url,
        batch_date=args.batch_date,
        master=args.master,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
