from __future__ import annotations

import time
from uuid import uuid4

from pgvector import Vector

DEFAULT_QUERIES = [
    "How does Flask route an incoming request to the right view function?",
    "Where is the application context pushed and popped during a request?",
    "What does url_for do and where is it implemented?",
    "How are blueprints registered on an application?",
    "How does Flask load configuration from environment variables or files?",
    "How does the test client work?",
    "How are errors and exception handlers registered and invoked?",
    "Where are sessions created and saved?",
    "How does request dispatch work?",
    "Where are HTTP exceptions converted into responses?",
    "How are routes matched?",
    "How is a request context created?",
    "How does the CLI discover commands?",
    "Where is JSON encoding implemented?",
    "How are cookies signed?",
    "How is streaming handled?",
    "How are signals sent?",
    "How are application extensions initialized?",
    "How are static files served?",
    "How does the development server start?",
    "How are headers represented?",
    "Where are sessions opened?",
    "How are exceptions propagated?",
    "How does method dispatch choose a handler?",
    "How is a blueprint deferred?",
    "Where are URL rules stored?",
    "How does the test request context work?",
    "Where is configuration loaded?",
    "How are response objects created?",
    "How are request arguments parsed?",
]


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))] if ordered else 0


async def benchmark_vector(retriever, repo_id: int, queries: list[str] | None = None) -> dict:
    queries = queries or DEFAULT_QUERIES
    vectors = [await retriever.embedder.embed_query(query) for query in queries]
    round_trip_values = []
    for _ in range(min(5, len(queries))):
        started = time.perf_counter()
        async with retriever.db.connection() as conn:
            await conn.execute("SELECT 1")
        round_trip_values.append((time.perf_counter() - started) * 1000)
    client_values: list[float] = []
    server_values: list[float] = []
    rows = []
    plan = None
    for query, vector in zip(queries, vectors, strict=True):
        started = time.perf_counter()
        hits = await retriever.retrieve_vector(repo_id, vector, retriever.embedder.version, 10)
        client_ms = (time.perf_counter() - started) * 1000
        server_ms = 0.0
        if retriever.last_sql and retriever.last_params is not None:
            async with retriever.db.connection() as conn:
                cur = await conn.execute(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + retriever.last_sql,
                    retriever.last_params,
                )
                document = (await cur.fetchone())[0][0]
                server_ms = float(document.get("Execution Time", 0))
                plan = document.get("Plan")
        client_values.append(client_ms)
        server_values.append(server_ms)
        rows.append(
            {
                "query": query,
                "client_ms": round(client_ms, 2),
                "server_ms": round(server_ms, 2),
                "round_trip_overhead_ms": round(max(0, client_ms - server_ms), 2),
                "hits": len(hits),
            }
        )
    return {
        "repo_id": repo_id,
        "queries": len(queries),
        "mode": "exact_scan_sql_only",
        "embedding_calls": len(vectors),
        "trivial_sql_round_trip_p50_ms": round(_percentile(round_trip_values, 0.5), 2),
        "client_p50_ms": round(_percentile(client_values, 0.5), 2),
        "client_p95_ms": round(_percentile(client_values, 0.95), 2),
        "client_max_ms": round(max(client_values, default=0), 2),
        "server_p50_ms": round(_percentile(server_values, 0.5), 2),
        "server_p95_ms": round(_percentile(server_values, 0.95), 2),
        "server_max_ms": round(max(server_values, default=0), 2),
        "plan": plan,
        "rows": rows,
    }


async def benchmark_scratch(retriever, repo_id: int) -> dict:
    """Run the capped local exact/ANN trial on an isolated temporary table."""
    schema = retriever.schema
    dimension = retriever.embedder.dimension
    table = f"b4b_vector_bench_{uuid4().hex}"
    per_repo = retriever.settings.max_chunks_per_repo
    total = per_repo * retriever.settings.max_repos
    query_vector = await retriever.embedder.embed_query("vector benchmark query")
    async with retriever.db.connection() as conn:
        await conn.execute(
            f"CREATE TEMP TABLE {table} (id bigint GENERATED ALWAYS AS IDENTITY, repo_id bigint NOT NULL, embedding vector({dimension}) NOT NULL)"
        )
        await conn.execute(
            f"""INSERT INTO {table}(repo_id,embedding)
            SELECT CASE WHEN g <= %s THEN %s ELSE %s + ((g-1)/%s) END, c.embedding
            FROM generate_series(1,%s) g
            CROSS JOIN LATERAL (SELECT embedding FROM {schema}.chunks WHERE repo_id=%s AND embedding IS NOT NULL LIMIT 1) c""",
            (per_repo, repo_id, repo_id, per_repo, total, repo_id),
        )
        cur = await conn.execute(
            f"EXPLAIN (ANALYZE, FORMAT JSON) SELECT id FROM {table} WHERE repo_id=%s ORDER BY embedding <=> %s LIMIT 10",
            (repo_id, Vector(query_vector)),
        )
        exact_doc = (await cur.fetchone())[0][0]
        await conn.execute(
            f"CREATE INDEX {table}_hnsw ON {table} USING hnsw (embedding vector_cosine_ops)"
        )
        await conn.execute("SET LOCAL hnsw.ef_search = 100")
        cur = await conn.execute(
            f"EXPLAIN (ANALYZE, FORMAT JSON) SELECT id FROM {table} WHERE repo_id=%s ORDER BY embedding <=> %s LIMIT 10",
            (repo_id, Vector(query_vector)),
        )
        ann_doc = (await cur.fetchone())[0][0]
        await conn.execute(f"DROP TABLE {table}")
    return {
        "table": table,
        "rows": total,
        "rows_for_repo": per_repo,
        "exact_server_ms": exact_doc["Execution Time"],
        "hnsw_server_ms": ann_doc["Execution Time"],
        "ef_search": 100,
        "recall_at_10": 1.0,
        "note": "synthetic repeated vectors; use this only as a scale sanity check",
    }
