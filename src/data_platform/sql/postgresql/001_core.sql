CREATE TABLE IF NOT EXISTS staging_orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    order_ts TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    amount_usd NUMERIC(18, 2) NOT NULL CHECK (amount_usd >= 0),
    source_updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_customers (
    customer_sk BIGSERIAL PRIMARY KEY,
    customer_id TEXT NOT NULL UNIQUE,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_orders (
    order_id TEXT PRIMARY KEY,
    customer_sk BIGINT NOT NULL REFERENCES dim_customers(customer_sk),
    order_ts TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    amount_usd NUMERIC(18, 2) NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS quarantined_orders (
    quarantine_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    error_reason TEXT NOT NULL,
    quarantined_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    input_rows INTEGER NOT NULL,
    accepted_rows INTEGER NOT NULL,
    quarantined_rows INTEGER NOT NULL,
    deduplicated_rows INTEGER NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT
);
