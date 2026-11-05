# repo-cartographer

Backend RAG service for asking questions about public GitHub repositories with grounded `file:line` citations. The system is built around PostgreSQL/pgvector, hybrid retrieval, AST-aware chunking, reranking, and incremental indexing.

## Local setup

1. Install Python 3.12 and [uv](https://docs.astral.sh/uv/).
2. Copy `backend/.env.example` to `backend/.env`.
3. Start PostgreSQL: `cd backend && make start-db`.
4. Install dependencies and apply the schema: `cd backend && uv sync && uv run cartographer db migrate`.
5. Run `uv run cartographer doctor`. Provider keys are intentionally optional until their provider milestones.

The local database uses the pgvector image `pgvector/pgvector:pg16` and exposes port `55432`. The test database is created alongside the development database.

## Working with repositories

All B1 operations are CLI-first and operate on public GitHub repositories:

```text
uv run cartographer repo add https://github.com/pallets/flask
uv run cartographer repo fetch 1
uv run cartographer repo check 1
uv run cartographer repo files 1 --json
uv run cartographer repo remove 1 --confirm
```

Registration validates and canonicalizes the URL, checks the remote default branch and HEAD, and stores only repository metadata. Fetching uses a depth-1, single-branch clone under `DATA_DIR/repos/<repo_id>/`; updates hard-reset and clean the clone, with atomic clone replacement and self-healing on corruption. Scanning uses committed paths from `git ls-files`, returns sorted SHA-256 inventories, and never writes the `files` or `chunks` tables.

The scanner excludes, in order: symlinks/non-regular files; generated/vendor/build dependency directories; lockfiles; license files; binary/media/archive/compiled/office formats; data formats; minified/generated filenames; configured custom globs; oversized or empty files; binary content; generated markers; minified/long-line content; and undecodable UTF-8. `include_globs` can rescue path rules 2–8. Documentation, configuration, tests, and unknown extensions are retained; language labels are emitted for the B2 chunker.

Known limitations: public GitHub HTTPS repositories only in production, default branch only, shallow snapshot rather than history, and no private-repository authentication. Local `file://` transports are available only through the injected test resolver.

## Chunking

B2 adds two read-only chunkers. `ast` uses tree-sitter for Python, TypeScript/TSX, and JavaScript/JSX; heading-aware sections for Markdown; whole-file or blank-line blocks for configuration; and a deterministic generic fallback for other languages. Oversized classes become bounded skeleton/member chunks, oversized functions split at line-safe boundaries, and tiny adjacent chunks merge when they fit. `fixed` is the structure-blind sliding line-window control.

The default budget is `max_chunk_tokens: 800`, with `min_chunk_tokens: 50` and three-line overlap only for the fixed/fallback line splitter. Counts use the configured tiktoken encoding as an approximation for the embedding provider. Missing grammar/tokenizer data is handled as an explicit fallback so an offline index run does not fail.

Example inspection commands (they do not write the database or call providers):

```text
uv run cartographer chunks stats 1 --json
uv run cartographer chunks show 1 src/flask/app.py
uv run cartographer chunks compare 1
uv run cartographer chunks tree 1 src/flask/app.py --depth 3
```

Final B2 demo summary:

| Repository | Files | Chunks | Median / p95 / max tokens | Below 50 | Above 800 | Time |
|---|---:|---:|---:|---:|---:|---:|
| pallets/flask | 218 | 1,388 | 95 / 778 / 800 | 443 | 0 | 2.8 s |
| avatar-nft-minter-bot-chain | 41 | 148 | 79 / 798 / 800 | 55 | 0 | 1.9 s |

The low-token chunks are mostly short reStructuredText release-note sections in Flask and import/config fragments in the NFT repository. They are retained for exact line coverage and citation honesty; they are candidates for future language-specific merging rather than dropped content. Tree-sitter process-level isolation remains out of scope, as specified by B2.

