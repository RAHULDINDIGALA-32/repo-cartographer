ALTER TABLE {{SCHEMA}}.repos
    ADD COLUMN IF NOT EXISTS pinned boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS repos_pinned_status_idx
    ON {{SCHEMA}}.repos(pinned, status);
