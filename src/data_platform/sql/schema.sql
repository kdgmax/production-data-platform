PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS staging_orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    order_ts TEXT NOT NULL,
    status TEXT NOT NULL,
    amount_usd REAL NOT NULL CHECK (amount_usd >= 0),
    source_updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_customers (
    customer_sk INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL UNIQUE,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_orders (
    order_id TEXT PRIMARY KEY,
    customer_sk INTEGER NOT NULL,
    order_ts TEXT NOT NULL,
    status TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    source_updated_at TEXT NOT NULL,
    FOREIGN KEY (customer_sk) REFERENCES dim_customers(customer_sk)
);

CREATE TABLE IF NOT EXISTS quarantined_orders (
    quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    error_reason TEXT NOT NULL,
    quarantined_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    input_rows INTEGER NOT NULL,
    accepted_rows INTEGER NOT NULL,
    quarantined_rows INTEGER NOT NULL,
    deduplicated_rows INTEGER NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS data_quality_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    check_name TEXT NOT NULL,
    violation_count INTEGER NOT NULL,
    passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
    checked_at TEXT NOT NULL
);

