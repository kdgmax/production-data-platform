"""Airflow 3 DAG for scheduled order-partition processing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from airflow.sdk import dag, get_current_context, task

from data_platform.orchestration import (
    evaluate_scheduled_run,
    logical_batch_date,
    run_scheduled_partition,
)


@dag(
    dag_id="orders_daily",
    description="Land, validate, load, and evaluate one daily order partition.",
    schedule="0 6 * * *",
    start_date=datetime(2026, 8, 25, tzinfo=UTC),
    catchup=True,
    max_active_runs=1,
    default_args={"owner": "data-platform"},
    tags=["data-engineering", "orders", "production"],
)
def build_orders_daily_dag():
    @task(task_id="resolve_partition")
    def resolve_partition() -> str:
        context = get_current_context()
        return logical_batch_date(context["logical_date"])

    @task(
        task_id="process_partition",
        retries=3,
        retry_delay=timedelta(minutes=1),
        retry_exponential_backoff=True,
        max_retry_delay=timedelta(minutes=15),
    )
    def process_partition(batch_date: str) -> dict:
        return run_scheduled_partition(batch_date)

    @task(task_id="evaluate_platform_slo")
    def evaluate_platform_slo(result: dict) -> dict:
        return evaluate_scheduled_run(result)

    batch_date = resolve_partition()
    result = process_partition(batch_date)
    evaluate_platform_slo(result)


orders_daily = build_orders_daily_dag()
