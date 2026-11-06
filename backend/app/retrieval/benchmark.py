from __future__ import annotations

import time

from app.models import QueryAnalysis

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


async def benchmark_vector(retriever, repo_id: int, queries: list[str] | None = None) -> dict:
    values = []
    rows = []
    for query in queries or DEFAULT_QUERIES:
        started = time.perf_counter()
        hits = await retriever.retrieve(
            repo_id, QueryAnalysis(original_query=query, rewritten_query=query), 10
        )
        elapsed = (time.perf_counter() - started) * 1000
        values.append(elapsed)
        rows.append({"query": query, "ms": round(elapsed, 2), "hits": len(hits)})
    ordered = sorted(values)

    def percentile(p):
        return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))] if ordered else 0

    return {
        "repo_id": repo_id,
        "queries": len(values),
        "p50_ms": round(percentile(0.5), 2),
        "p95_ms": round(percentile(0.95), 2),
        "max_ms": round(max(values, default=0), 2),
        "rows": rows,
        "mode": "exact_scan",
    }
