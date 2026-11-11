ALTER TABLE {{SCHEMA}}.repos
    ADD COLUMN IF NOT EXISTS remote_sha text,
    ADD COLUMN IF NOT EXISTS remote_checked_at timestamptz;

ALTER TABLE {{SCHEMA}}.jobs
    ADD COLUMN IF NOT EXISTS trigger text NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS error_code text,
    ADD COLUMN IF NOT EXISTS result jsonb,
    ADD COLUMN IF NOT EXISTS worker_id text;

ALTER TABLE {{SCHEMA}}.jobs
    DROP CONSTRAINT IF EXISTS jobs_trigger_check;
ALTER TABLE {{SCHEMA}}.jobs
    ADD CONSTRAINT jobs_trigger_check CHECK (trigger IN ('manual','scheduler','lazy_check','api','webhook'));

CREATE INDEX IF NOT EXISTS repos_remote_checked_idx ON {{SCHEMA}}.repos(remote_checked_at);
CREATE INDEX IF NOT EXISTS jobs_repo_created_idx ON {{SCHEMA}}.jobs(repo_id, created_at);
CREATE INDEX IF NOT EXISTS jobs_status_run_after_idx ON {{SCHEMA}}.jobs(status, run_after);
