# repo-cartographer

Backend RAG service for asking questions about public GitHub repositories with grounded `file:line` citations. The system is built around PostgreSQL/pgvector, hybrid retrieval, AST-aware chunking, reranking, and incremental indexing.

## Local setup

1. Install Python 3.12 and [uv](https://docs.astral.sh/uv/).
2. Copy `.env.example` to `.env`.
3. Start PostgreSQL: `make start-db`.
4. Install dependencies and apply the schema: `cd backend && uv sync`, then `uv run cartographer db migrate`.
5. Run `uv run cartographer doctor`. Provider keys are intentionally optional in B0; later milestones use them.

The local database uses the pgvector image `pgvector/pgvector:pg16` and exposes port `55432`. The test database is created alongside the development database.

