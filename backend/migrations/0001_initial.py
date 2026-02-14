from yoyo import step

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS signals (
            id SERIAL PRIMARY KEY,
            source TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT,
            topics JSONB DEFAULT '[]',
            score REAL DEFAULT 0,
            collected_at TEXT NOT NULL,
            run_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signal_narratives (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            confidence TEXT,
            direction TEXT,
            explanation TEXT,
            signal_count INTEGER DEFAULT 0,
            generated_at TEXT NOT NULL,
            run_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            total_signals INTEGER DEFAULT 0,
            total_narratives INTEGER DEFAULT 0,
            signal_summary JSONB
        );
        CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source);
        CREATE INDEX IF NOT EXISTS idx_signals_collected ON signals(collected_at);
        CREATE INDEX IF NOT EXISTS idx_signals_run ON signals(run_id);
        CREATE INDEX IF NOT EXISTS idx_snarr_run ON signal_narratives(run_id);
        CREATE TABLE IF NOT EXISTS narrative_store (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            canonical_name TEXT,
            status TEXT DEFAULT 'ACTIVE',
            first_detected TIMESTAMPTZ,
            last_detected TIMESTAMPTZ,
            last_updated TIMESTAMPTZ,
            faded_at TIMESTAMPTZ,
            detection_count INTEGER DEFAULT 0,
            missed_count INTEGER DEFAULT 0,
            current_confidence TEXT DEFAULT 'MEDIUM',
            current_direction TEXT DEFAULT 'EMERGING',
            explanation TEXT,
            trend_evidence TEXT,
            market_opportunity TEXT,
            topics JSONB DEFAULT '[]',
            all_signals JSONB DEFAULT '[]',
            ideas JSONB DEFAULT '[]',
            references_ JSONB DEFAULT '[]',
            confidence_history JSONB DEFAULT '[]',
            direction_history JSONB DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS narrative_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """,
        """
        DROP TABLE IF EXISTS narrative_meta;
        DROP TABLE IF EXISTS narrative_store;
        DROP TABLE IF EXISTS signal_narratives;
        DROP TABLE IF EXISTS signals;
        DROP TABLE IF EXISTS runs;
        """
    )
]
