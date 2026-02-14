from yoyo import step

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS email_subscribers (
            id BIGSERIAL PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            subscribed_at TIMESTAMPTZ DEFAULT NOW(),
            verified BOOLEAN DEFAULT FALSE,
            verify_token TEXT NOT NULL,
            unsubscribe_token TEXT NOT NULL,
            frequency TEXT NOT NULL DEFAULT 'weekly' CHECK (frequency IN ('daily', 'weekly')),
            last_sent_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_subscribers_email ON email_subscribers(email);
        CREATE INDEX IF NOT EXISTS idx_subscribers_frequency ON email_subscribers(frequency);
        CREATE INDEX IF NOT EXISTS idx_subscribers_unsubscribe_token ON email_subscribers(unsubscribe_token);
        """,
        """
        DROP TABLE IF EXISTS email_subscribers;
        """
    ),
]
