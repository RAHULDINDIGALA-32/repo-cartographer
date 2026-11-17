# Operations runbook

Local development and automated tests use Docker PostgreSQL on port `55432` and
the dedicated `cartographer_test` database. Hosted/demo runs use Supabase. Never
run destructive test fixtures or crash-recovery experiments against Supabase.

Apply migrations before a release:

```text
uv run cartographer db migrate
uv run cartographer doctor
```

Keep `API_RUN_WORKER=false` until the B7 verification gate is green. After a
chunker, enricher, embedder, or vector-dimension change, run `index plan`,
review projected cost, and re-index at the pinned commit.

```text
uv run cartographer index plan <repo_id>
uv run cartographer index sync <repo_id> --no-fetch --yes
uv run cartographer jobs list --json
uv run cartographer scheduler status
uv run cartographer queries prune
```

`/metrics` and `/v1/admin/stats` require the admin key. Metrics use bounded
labels and are intended for a private scraper. Budget exhaustion is a controlled
429; provider outages surface typed errors.

Start the API with `uv run cartographer-api` (or `python -m app.serve`). This
launcher is required on Windows because psycopg async pools cannot run on the
default Proactor event loop; it selects the compatible loop before Uvicorn
starts.

| Symptom | First check | Fix |
|---|---|---|
| `/ready` is 503 | `doctor`, `db status` | Apply migrations or fix vector dimension |
| asks are 429 | `/v1/admin/stats` | Wait for rate/budget recovery or adjust policy |
| repo is stale | `scheduler status`, `jobs list` | Inspect the coalesced sync job |
| provider errors | `provider ping`, logs | Rotate key, verify model/access, or wait |
| clone missing after restart | `index status` | Run `index sync`; database index rows persist |
