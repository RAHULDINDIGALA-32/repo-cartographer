ALTER TABLE {{SCHEMA}}.repos
    ADD COLUMN IF NOT EXISTS public boolean NOT NULL DEFAULT true;

CREATE TABLE IF NOT EXISTS {{SCHEMA}}.webhook_deliveries (
    delivery_id text PRIMARY KEY,
    received_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS webhook_deliveries_received_idx
    ON {{SCHEMA}}.webhook_deliveries(received_at);
