CREATE SCHEMA IF NOT EXISTS {{SCHEMA}};
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
CREATE TABLE IF NOT EXISTS {{SCHEMA}}.schema_migrations (version integer PRIMARY KEY, name text NOT NULL, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS {{SCHEMA}}.schema_meta (key text PRIMARY KEY, value text NOT NULL);
INSERT INTO {{SCHEMA}}.schema_meta(key, value) VALUES ('embedding_dim', '{{EMBEDDING_DIM}}') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
