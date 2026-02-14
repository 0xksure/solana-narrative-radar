from yoyo import step

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS narrative_signal_history (
            id BIGSERIAL PRIMARY KEY,
            narrative_id TEXT NOT NULL,
            signal JSONB NOT NULL,
            pipeline_run INTEGER,
            detected_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_signal_hist_narrative ON narrative_signal_history(narrative_id);
        CREATE INDEX IF NOT EXISTS idx_signal_hist_detected ON narrative_signal_history(detected_at DESC);
        CREATE INDEX IF NOT EXISTS idx_signal_hist_narrative_detected ON narrative_signal_history(narrative_id, detected_at DESC);

        CREATE TABLE IF NOT EXISTS narrative_snapshots (
            id BIGSERIAL PRIMARY KEY,
            narrative_id TEXT NOT NULL,
            name TEXT,
            status TEXT,
            confidence TEXT,
            direction TEXT,
            signal_count INTEGER DEFAULT 0,
            pipeline_run INTEGER,
            snapshot_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_narrative ON narrative_snapshots(narrative_id, snapshot_at DESC);
        """,
        """
        DROP TABLE IF EXISTS narrative_snapshots;
        DROP TABLE IF EXISTS narrative_signal_history;
        """
    )
]
