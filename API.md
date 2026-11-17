# Repo Cartographer API v1

The API is served under `/v1`. `GET /health` is a liveness check and does not
touch PostgreSQL. `GET /ready` checks the database, migrations, vector
dimension, and reports whether the optional in-process worker is enabled,
including its process age when enabled and a reason when disabled.

## Authentication

Read-only repository and ask routes are public. Administrative routes require
`X-API-Key`; keys are configured through `API_ADMIN_KEYS` and are compared in
constant time. Swagger exposes this as an API-key security scheme in the
**Authorize** dialog. Clients that standardize on bearer headers may use
`Authorization: Bearer <admin-key>` as an alias. Keys are never returned or
written to logs/query records.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness |
| GET | `/ready` | none | Readiness |
| GET | `/v1/repos` | none | Public repository list |
| GET | `/v1/repos/{id}` | none | Repository and recent runs |
| POST | `/v1/repos` | admin | Register and optionally enqueue |
| DELETE | `/v1/repos/{id}` | admin | Delete repository and clone |
| POST | `/v1/repos/{id}/sync` | admin | Enqueue sync/full reindex |
| GET | `/v1/repos/{id}/jobs` | admin | Job history |
| POST | `/v1/repos/{id}/ask` | rate limited | Grounded answer |
| POST | `/v1/feedback` | rate limited | Store rating |
| GET | `/v1/queries/{id}` | admin | Query log and trace |
| GET | `/v1/admin/stats` | admin | Aggregate operational statistics |
| GET | `/v1/admin/queries` | admin | Query explorer with cursor pagination |
| POST | `/v1/webhooks/github` | signature | Optional signed push freshness trigger |

Registering a repository:

```json
POST /v1/repos
X-API-Key: <admin-key>
{"url":"https://github.com/pallets/flask","enqueue":true}
```

Ask requests use `{ "question": "...", "stream": true, "options": {"k": 8} }`.
Set `options.include_context=true` only for an inspector UI; it includes capped
assembled block text. Citation payloads include a capped `snippet` and
`snippet_truncated` flag.
Clients must not automatically retry POST asks because a retry can spend provider
tokens twice.

## SSE

Streaming asks return `text/event-stream`. Every event has an incrementing `id`,
an `event` name, and JSON `data`:

```text
id: 1
event: retrieval
data: {"count":8}

id: 2
event: token
data: {"text":"..."}

id: 3
event: citations
data: {"citations":[]}

id: 4
event: done
data: {"query_log_id":42,"staleness":{}}
```

Supported events are `retrieval`, `status`, `token`, `citations`, `done`, and
`error`. `: ping` comment frames are heartbeats. `done` or `error` is terminal;
clients should not reconnect and replay an ask automatically. Disconnects cancel
the active stream and release the concurrency slot.

Non-streaming asks return the assembled `answer`, all event payloads, and the
terminal `done` payload.

## Errors and limits

`GET /metrics` is outside `/v1` and requires the admin key. It returns bounded
Prometheus-compatible text labels for HTTP, ask, provider, and job activity.

The GitHub webhook is disabled when `GITHUB_WEBHOOK_SECRET` is empty. When
enabled, configure GitHub for JSON push events and send the raw body with
`X-Hub-Signature-256` and `X-GitHub-Delivery`; duplicate delivery IDs are
ignored.

Errors use:

```json
{"error":{"code":"rate_limited","message":"...","retryable":true,"request_id":"..."}}
```

Validation errors are 422; missing/invalid admin credentials are 401/403;
not-found is 404; conflicts and unready repositories are 409; oversized bodies
are 413; provider failures are 502/504; rate, budget, and concurrency failures
are 429/503. `Retry-After` is returned for 429/503.

Default limits are six ask requests/minute with a burst of three, ten write
requests/minute, four concurrent asks, and a daily token/client guard. These
are process-local; multi-instance deployments require a shared limiter before
scaling out.

## Freshness and CORS

Ask `done` payloads carry B7 staleness fields: `indexed_sha`, `indexed_at`,
`remote_sha`, `remote_checked_at`, `is_stale`, `sync`, and `message`. `GET /v1/queries/{id}` also returns bounded `chunk_metadata` for trace-referenced chunks (`id`, path, line range, symbol, type, token count), never chunk text. CORS is an
explicit configured origin list; wildcard CORS is rejected in production.
