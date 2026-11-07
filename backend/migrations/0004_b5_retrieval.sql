CREATE INDEX chunks_symbol_lookup_idx ON {{SCHEMA}}.chunks(repo_id, lower(symbol)) WHERE symbol IS NOT NULL;
CREATE INDEX chunks_parent_symbol_lookup_idx ON {{SCHEMA}}.chunks(repo_id, lower(parent_symbol)) WHERE parent_symbol IS NOT NULL;
ALTER TABLE {{SCHEMA}}.query_logs ADD COLUMN trace jsonb NOT NULL DEFAULT '{}'::jsonb;
