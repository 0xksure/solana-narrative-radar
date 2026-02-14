from yoyo import step

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS analytics_events (
            id BIGSERIAL PRIMARY KEY,
            app TEXT NOT NULL,
            event TEXT NOT NULL,
            properties JSONB DEFAULT '{}',
            session_id TEXT,
            ip_hash TEXT,
            user_agent TEXT,
            referrer TEXT,
            path TEXT,
            country TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_events_app ON analytics_events(app);
        CREATE INDEX IF NOT EXISTS idx_events_event ON analytics_events(event);
        CREATE INDEX IF NOT EXISTS idx_events_created ON analytics_events(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_events_app_event ON analytics_events(app, event, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_events_path ON analytics_events(path);
        
        CREATE TABLE IF NOT EXISTS analytics_daily_rollup (
            id SERIAL PRIMARY KEY,
            app TEXT NOT NULL,
            event TEXT NOT NULL,
            date DATE NOT NULL,
            count INTEGER DEFAULT 0,
            unique_sessions INTEGER DEFAULT 0,
            properties_summary JSONB DEFAULT '{}',
            UNIQUE(app, event, date)
        );
        CREATE INDEX IF NOT EXISTS idx_rollup_app_date ON analytics_daily_rollup(app, date DESC);
        """,
        """
        DROP TABLE IF EXISTS analytics_daily_rollup;
        DROP TABLE IF EXISTS analytics_events;
        """
    )
]
