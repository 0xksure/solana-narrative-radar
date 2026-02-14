from yoyo import step

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS telegram_subscribers (
            id BIGSERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL UNIQUE,
            username TEXT,
            subscribed_at TIMESTAMPTZ DEFAULT NOW(),
            active BOOLEAN DEFAULT TRUE,
            preferences JSONB DEFAULT '{}'::jsonb
        );
        CREATE INDEX IF NOT EXISTS idx_tg_subs_chat_id ON telegram_subscribers(chat_id);
        CREATE INDEX IF NOT EXISTS idx_tg_subs_active ON telegram_subscribers(active);
        """,
        """
        DROP TABLE IF EXISTS telegram_subscribers;
        """
    ),
]
