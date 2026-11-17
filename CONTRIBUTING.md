# Contributing to Repo Cartographer

Thanks for helping improve a grounded, inspectable RAG system. This document is the working agreement for local setup, style, tests, and pull requests. Product behavior is described in the [README](README.md); API, deploy, security, and operations details live under [`docs/`](docs/).

## Ways to contribute

- Bug reports with reproduction steps, `X-Request-ID` if available, and whether `/health` and `/ready` succeeded.
- Retrieval or generation quality notes **with the indexed commit SHA**, repository URL, question, and (if possible) the gold path/line you expected.
- Documentation fixes and clarifications.
- Code: ingestion, retrieval presets, API/SSE, jobs, frontend UX, tests, and eval gold (human-verified only).

Please do **not** open PRs that add private-repository auth, arbitrary URL fetching, or exploit payloads. Public GitHub HTTPS is the production scope.

## Ground rules

1. **No secrets in git.** `.env`, provider keys, admin keys, webhook secrets, and database URLs stay in the host environment. Pipeline snapshots and query logs must not contain them.
2. **Do not execute repository source.** Ingestion hashes and reads files; it never runs them.
3. **Treat indexed code as untrusted.** Prompt delimiters and injection hardening in `app/generation/prompt.py` are load-bearing — do not “simplify” them away.
4. **Do not auto-retry `POST /ask` in clients.** A retry can spend provider tokens twice.
5. **Gold evidence is human-owned.** `eval/questions.yaml` entries must be verified at the indexed commit. Do not generate gold paths from an LLM and merge them unverified.
6. **Never run destructive fixtures against hosted/demo Postgres.** Local tests use `cartographer_test` on port `55432`.

## Development setup

### Prerequisites

- Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 20.11+, Docker
- Optional: Voyage and generator keys for live index/ask paths. Unit tests do not require them; tests marked `network` do.

### Backend

```bash
cp backend/.env.example backend/.env
# Host CLI: DATABASE_URL=...@localhost:55432/cartographer
make start-db
cd backend
uv sync
uv run cartographer db migrate
uv run cartographer doctor
uv run cartographer-api
```

Use `uv run cartographer-api` (or `python -m app.serve`) rather than a raw Uvicorn invocation on Windows — the launcher selects an event loop compatible with psycopg’s async pool.

### Frontend

```bash
cd frontend
cp .env.example .env.local
# NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
# Do not put API_ADMIN_KEYS or provider keys in NEXT_PUBLIC_*
npm install
npm run dev
```

### Useful commands

| Intent | Command |
| --- | --- |
| Lint backend | `cd backend && uv run ruff check app tests` |
| Test backend | `cd backend && uv run pytest -q` |
| Validate gold set | `cd backend && uv run cartographer eval validate --path ../eval/questions.yaml` |
| Frontend checks | `cd frontend && npm run typecheck && npm run lint && npm run format:check && npm test && npm run build` |
| Refresh OpenAPI types | `cd frontend && npm run gen:api` (from the committed `docs/openapi.json`, never a live server) |

Keep `node_modules` and `.next` off OneDrive when possible; file locking can break esbuild on Windows. CI is the clean-environment source of truth.

## Project conventions

### Backend

- Python 3.12, Ruff (`E,F,I,UP,B`), line length 100.
- Domain errors go through `app.core.errors.AppError` so the API can emit `{ "error": { "code", "message", "retryable", "request_id" } }`.
- Provider keys and host policy live in `.env` / `Settings`. `config.yaml` holds only pipeline *specs* (chunker, model name, token budgets). Do not log secrets; do not persist them in `query_logs.pipeline_config`.
- Index writes are atomic **per file**. Advance `indexed_sha` only after a successful run.
- Retriever/generator/chunker implementations register through `app.interfaces.registry`. Prefer a preset in `eval/presets.yaml` over silent default changes.
- SSE event names and shapes are a public contract (`retrieval`, `status`, `token`, `citations`, `done`, `error`). Additive fields are safer than renames.

### Frontend

- App Router, TypeScript, ESLint (`eslint-config-next`), Prettier.
- Typed fetch/SSE client in `src/api`; Zod validates SSE at runtime because the OpenAPI snapshot cannot express the stream.
- Admin key: React memory by default; optional `sessionStorage` only. Never `localStorage`, URLs, React Query keys, or logs.
- Respect `prefers-reduced-motion`. Do not add per-token animations.
- Share links may prefill `?q=` but must not auto-submit.

### Docs

If you change request/response shapes, update `docs/api.md` and regenerate or hand-edit `docs/openapi.json` in the same PR. Deploy, security, and operations docs should move with behavior, not after.

## Tests

- Backend tests expect Docker Postgres (`pgvector/pgvector:pg16`) and `TEST_DATABASE_URL`.
- Prefer fast, offline tests. Mark live provider calls with `network`.
- Frontend: Vitest + Testing Library. Cover SSE parsing, history, and admin session behavior when you touch those paths.
- A PR that changes retrieval ranking should include eval output (preset, split, and a short interpretation). Do not retitle a preset the “default” without tune + heldout (+ non-famous repo) numbers.

CI (`.github/workflows/ci.yml`) runs backend lint/tests/eval-validate/image build and frontend typecheck/lint/format/test/build on every push and pull request.

## Pull requests

1. Branch from `main`. Keep the change set focused (ingestion vs retrieval vs API vs UI vs docs).
2. Describe **why**, the user-visible effect, and how you tested.
3. Include screenshots or a short clip for UI changes; include request IDs or eval tables for backend behavior.
4. Do not skip CI (`--no-verify`) or commit generated junk (`backend/.pytest-tmp*`, `.next`, local clones under `DATA_DIR`).
5. Expect review on: secret handling, citation/prompt contracts, job idempotency, SSE compatibility, and eval honesty.

Suggested title prefixes: `fix(backend):`, `feat(frontend):`, `docs:`, `eval:`, `chore:`.

## Security reports

If you believe you found a vulnerability (prompt injection that actually steers answers, admin-key leak, webhook bypass, path traversal on clones), **do not** file a public issue with a working exploit. Email or message the maintainer privately. Public GitHub-only scope does not mean admin routes or keys are in-bounds for drive-by testing on the live demo.

## License

By contributing, you agree that your work is licensed under the [MIT License](LICENSE), the same as the rest of the repository.
