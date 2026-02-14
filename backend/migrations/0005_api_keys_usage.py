from yoyo import step

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id SERIAL PRIMARY KEY,
            key_hash TEXT UNIQUE NOT NULL,
            key_prefix TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            tier TEXT NOT NULL DEFAULT 'free' CHECK (tier IN ('free', 'pro', 'enterprise')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_used_at TIMESTAMPTZ,
            requests_today INTEGER NOT NULL DEFAULT 0,
            requests_total BIGINT NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
        CREATE INDEX IF NOT EXISTS idx_api_keys_email ON api_keys(email);
        """,
        """
        DROP TABLE IF EXISTS api_keys;
        """
    ),
    step(
        """
        CREATE TABLE IF NOT EXISTS api_usage_log (
            id SERIAL PRIMARY KEY,
            api_key_id INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
            ip_hash TEXT,
            endpoint TEXT NOT NULL,
            method TEXT NOT NULL DEFAULT 'GET',
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            response_time_ms INTEGER,
            status_code INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_api_usage_log_timestamp ON api_usage_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_api_usage_log_api_key_id ON api_usage_log(api_key_id);
        """,
        """
        DROP TABLE IF EXISTS api_usage_log;
        """
    ),
]
