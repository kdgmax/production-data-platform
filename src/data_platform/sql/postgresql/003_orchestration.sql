ALTER TABLE pipeline_runs ADD COLUMN batch_date DATE;
ALTER TABLE pipeline_runs ADD COLUMN trigger_type TEXT NOT NULL DEFAULT 'manual';

CREATE TABLE IF NOT EXISTS pipeline_locks (
    lock_name TEXT PRIMARY KEY,
    owner_run_id TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

