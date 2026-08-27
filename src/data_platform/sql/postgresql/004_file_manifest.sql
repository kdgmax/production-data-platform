CREATE TABLE IF NOT EXISTS file_manifest (
    manifest_id BIGSERIAL PRIMARY KEY,
    file_uri TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL UNIQUE,
    size_bytes BIGINT NOT NULL,
    etag TEXT,
    batch_date DATE,
    status TEXT NOT NULL CHECK (status IN ('processing', 'succeeded', 'failed')),
    discovered_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ,
    run_id TEXT,
    error_message TEXT
);

