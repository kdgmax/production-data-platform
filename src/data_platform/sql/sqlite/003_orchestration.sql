ALTER TABLE pipeline_runs ADD COLUMN batch_date TEXT;
ALTER TABLE pipeline_runs ADD COLUMN trigger_type TEXT NOT NULL DEFAULT 'manual';

CREATE TABLE IF NOT EXISTS pipeline_locks (
    lock_name TEXT PRIMARY KEY,
    owner_run_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

