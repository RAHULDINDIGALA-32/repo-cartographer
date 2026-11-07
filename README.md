# repo-cartographer

Backend RAG service for asking questions about public GitHub repositories with grounded `file:line` citations. The system is built around PostgreSQL/pgvector, dense retrieval, AST-aware chunking, and incremental indexing. Hybrid retrieval and reranking are planned for B5.

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

B2 adds two read-only chunkers. `ast` uses tree-sitter for Python, TypeScript/TSX, JavaScript/JSX, and Solidity when the installed grammar is available; heading-aware sections for Markdown; whole-file or blank-line blocks for configuration; and a deterministic generic fallback for other languages. Oversized classes become bounded skeleton/member chunks, oversized functions split at line-safe boundaries, and tiny adjacent chunks merge when they fit. `fixed` is the structure-blind sliding line-window control.

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

## Indexing

B3 turns chunks into searchable Postgres rows through this flow: scan → chunk → deterministic enrichment → cross-repository embedding reuse lookup → bounded Voyage batches → atomic per-file writes. The enrichment header is deterministic and is kept separate from the cited chunk text:

```text
path: src/example.py
language: Python
symbol: Parser.parse (method, part 1/2)
lines: 40-66

<exact source slice>
```

`content_hash` is SHA-256 over the exact header-plus-source embedding text. A vector is reusable only when both `content_hash` and `embedder_version` match, including across repositories. `index estimate` performs the full scan/chunk/enrich/reuse analysis without making provider calls; use it before `index run` to size token spend and rate-limit time. `index run` writes each file atomically, advances `indexed_sha` only after the complete run succeeds, and records retry/throttle/fallback statistics.

The embedding provider receives repository source text and deterministic metadata. This project indexes public repositories only; users should treat source text as leaving the local machine when Voyage embedding is enabled. Provider keys are never logged or committed. The implementation follows Voyage’s current embeddings API contract for document input, explicit `output_dimension`, and the configured model’s batch limits: [Voyage embeddings API](https://docs.voyageai.com/reference/embeddings-api).

Use `index verify <repo_id>` before B4 retrieval work. It checks embeddings, versions, generated full-text search data, file/chunk referential integrity, line ranges, and sub-minimum chunk counts. B3 does not create a vector index; B4 owns that benchmark and decision.

## Asking questions

B4 provides exact dense retrieval followed by context deduplication, a token budget, a grounded Claude prompt, and structural citation validation. Repository content is treated as untrusted data inside delimiters; the generator is instructed to ignore instructions found in source code and to say when evidence is insufficient. This is single-turn, dense-only retrieval: sparse search, fusion, reranking, query rewriting, semantic faithfulness checks, and remote staleness checks are deferred to later milestones.

```text
uv run cartographer ask <repo_id> "Where does Flask dispatch a request?"
uv run cartographer ask <repo_id> "Where does Flask dispatch a request?" --no-generate --show-context
uv run cartographer ask <repo_id> "Where does Flask dispatch a request?" --path src/flask --k 8
uv run cartographer bench vector <repo_id> --json
```

Answers cite context blocks as `[1]` or `[1][3]`. The CLI prints the cited source path, line range, commit permalink, stage timings, and token usage. Citation validation is structural only: it confirms that cited block numbers exist and ignores markers inside inline or fenced code, but it does not prove that a citation semantically supports a claim.

## Retrieval

B5 adds optional rule or LLM query analysis, dense/sparse/symbol signals, weighted reciprocal-rank fusion, optional Voyage reranking, score priors, and assembler safeguards for duplicate or over-represented files. Select an ablation with `--preset`, inspect retrieval without generation using `--no-generate`, and print the sanitized trace with `--trace`:

```text
uv run cartographer ask <repo_id> "Where is request dispatch implemented?" --preset hybrid3_rule --no-generate --trace
uv run cartographer eval validate
uv run cartographer eval retrieval <repo_id> --split tune --preset hybrid3 --path ../eval/questions.yaml
```

The B5 gold evidence is human-owned and must be verified at the indexed commit. An LLM analyzer can benefit from prior knowledge of famous repositories, so comparisons must include the less familiar NFT repository. Retrieval metrics are not generation-quality or faithfulness metrics; those belong to Project 4. A deployed backend should run in the same region as its database because developer-laptop round trips are not representative.

## LLM providers

The active generator is an `LLMSpec` in `config.yaml`; it contains only the provider name, model, sampling temperature, and output-token limit. API keys, endpoints, timeouts, concurrency, and rate limits live in `.env` and are never stored in `query_logs.pipeline_config`. Built-in profiles are `anthropic`, `groq`, `openrouter`, and `custom` OpenAI-compatible endpoints. Switch providers by changing the generator spec, then run `uv run cartographer provider list` and `uv run cartographer provider ping $providerName --model $modelName` before asking questions. Use `ask --debug` for sanitized provider error codes and causes.

Groq and OpenRouter are OpenAI-compatible but have different model catalogs, limits, and data-routing policies. OpenRouter free variants may route through third-party providers with different retention policies; use them only for public repository data and verify the selected model/provider policy before use. Changing the embedding provider remains a re-indexing operation because it changes `embedder_version` and vector dimension.

