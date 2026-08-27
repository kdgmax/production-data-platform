CREATE TABLE IF NOT EXISTS file_manifest (
    manifest_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_uri TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL,
    etag TEXT,
    batch_date TEXT,
    status TEXT NOT NULL CHECK (status IN ('processing', 'succeeded', 'failed')),
    discovered_at TEXT NOT NULL,
    processed_at TEXT,
    run_id TEXT,
    error_message TEXT
);

