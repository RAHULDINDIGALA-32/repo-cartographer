ALTER TABLE {{SCHEMA}}.chunks ADD COLUMN IF NOT EXISTS enricher_version text NOT NULL DEFAULT '';
ALTER TABLE {{SCHEMA}}.repos ADD COLUMN IF NOT EXISTS indexed_at timestamptz;
ALTER TABLE {{SCHEMA}}.index_runs ADD COLUMN IF NOT EXISTS stats jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE {{SCHEMA}}.index_runs ADD COLUMN IF NOT EXISTS embed_requests integer NOT NULL DEFAULT 0;
ALTER TABLE {{SCHEMA}}.index_runs ADD COLUMN IF NOT EXISTS rate_limit_wait_ms bigint NOT NULL DEFAULT 0;
