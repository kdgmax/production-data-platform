CREATE TABLE IF NOT EXISTS data_quality_results (
    result_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    check_name TEXT NOT NULL,
    violation_count INTEGER NOT NULL,
    passed BOOLEAN NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL
);

