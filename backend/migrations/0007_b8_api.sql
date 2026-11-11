ALTER TABLE {{SCHEMA}}.feedback
    ADD COLUMN IF NOT EXISTS client_key text;

CREATE UNIQUE INDEX IF NOT EXISTS feedback_query_client_unique
    ON {{SCHEMA}}.feedback(query_log_id, client_key)
    WHERE client_key IS NOT NULL;
