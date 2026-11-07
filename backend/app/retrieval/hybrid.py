from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from psycopg import Error as PsycopgError

from app.core.errors import DatabaseError
from app.models import QueryAnalysis, RetrievalHit
from app.retrieval.dense import DenseRetriever
from app.retrieval.sparse import SparseRetriever, SymbolRetriever


class WeightedRRF:
    name = "rrf"
    version = "rrf:weighted-v1"

    def __init__(self, config=None, **_: object):
        self.config = config
        self.last_trace: dict = {}

    def fuse(self, ranked_lists: list[list[RetrievalHit]], top_k: int, weights=None, labels=None):
        weights = weights or [1.0] * len(ranked_lists)
        labels = labels or [str(index) for index in range(len(ranked_lists))]
        scores = defaultdict(float)
        ranks: dict[int, dict[str, int]] = defaultdict(dict)
        hits: dict[int, RetrievalHit] = {}
        for values, weight, label in zip(ranked_lists, weights, labels, strict=True):
            for rank, hit in enumerate(values, 1):
                chunk_id = hit.chunk.id
                scores[chunk_id] += float(weight) / (
                    self.config.rrf_k + rank if self.config else 60 + rank
                )
                ranks[chunk_id][label] = rank
                hits.setdefault(chunk_id, hit)
        ordered = sorted(
            hits,
            key=lambda chunk_id: (
                -scores[chunk_id],
                min(ranks[chunk_id].values()),
                chunk_id,
            ),
        )[:top_k]
        result = [
            hits[chunk_id].model_copy(
                update={"score": scores[chunk_id], "rank": rank, "source": "fused"}
            )
            for rank, chunk_id in enumerate(ordered, 1)
        ]
        self.last_trace = {
            "items": [
                {
                    "id": hit.chunk.id,
                    "score": hit.score,
                    "rank": hit.rank,
                    "per_list_ranks": ranks[hit.chunk.id],
                }
                for hit in result
            ]
        }
        return result


class HybridRetriever:
    name = "hybrid"
    version = "hybrid:1"

    def __init__(
        self,
        db=None,
        settings=None,
        config=None,
        embedder=None,
        dense=None,
        sparse=None,
        symbol=None,
        fuser=None,
        **_: object,
    ):
        self.config = config
        self.embedder = embedder
        self.dense = dense or DenseRetriever(
            db=db, settings=settings, config=config, embedder=embedder
        )
        self.sparse = sparse or SparseRetriever(db=db, settings=settings)
        self.symbol = symbol or SymbolRetriever(db=db, settings=settings)
        self.fuser = fuser or WeightedRRF(config=config)
        self.last_trace: dict = {}
        self.degraded: list[str] = []
        self.last_latencies: dict[str, int] = {}
        self.last_indexed_sha: str | None = None
        self.last_status: str | None = None

    async def retrieve(
        self, repo_id: int, analysis: QueryAnalysis, top_k: int, **kwargs
    ) -> list[RetrievalHit]:
        self.degraded = []
        self.last_latencies = {}
        sources = set(self.config.hybrid_sources if self.config else ("dense", "sparse", "symbol"))
        lists: list[list[RetrievalHit]] = []
        labels: list[str] = []
        weights: list[float] = []

        async def dense_values():
            texts = [analysis.rewritten_query, *analysis.sub_queries]
            started = time.perf_counter()
            vectors = await self.embedder.embed_queries(texts)
            self.last_latencies["embed_query"] = round((time.perf_counter() - started) * 1000)
            output = []
            for vector in vectors:
                output.append(
                    await self.dense.retrieve_vector(
                        repo_id, vector, self.embedder.version, self.config.top_k_dense, **kwargs
                    )
                )
            return output

        tasks = {}

        async def timed(name, awaitable):
            started = time.perf_counter()
            try:
                return await awaitable
            finally:
                self.last_latencies[f"retrieve_{name}"] = round(
                    (time.perf_counter() - started) * 1000
                )

        if "dense" in sources:
            tasks["dense"] = asyncio.create_task(timed("dense", dense_values()))
        if "sparse" in sources:
            tasks["sparse"] = asyncio.create_task(
                timed(
                    "sparse",
                    self.sparse.retrieve(repo_id, analysis, self.config.top_k_sparse, **kwargs),
                )
            )
        if "symbol" in sources:
            tasks["symbol"] = asyncio.create_task(
                timed(
                    "symbol",
                    self.symbol.retrieve(repo_id, analysis, self.config.top_k_symbol, **kwargs),
                )
            )
        results = {}
        for name, task in tasks.items():
            try:
                results[name] = await task
            except (DatabaseError, PsycopgError):
                raise
            except Exception:
                self.degraded.append(name)
        if "dense" in results:
            dense_lists = results["dense"]
            self.last_indexed_sha = getattr(self.dense, "last_indexed_sha", None)
            self.last_status = getattr(self.dense, "last_status", None)
            lists.append(dense_lists[0] if dense_lists else [])
            labels.append("dense")
            weights.append(self.config.fusion_weights.get("dense", 1.0))
            for index, values in enumerate(dense_lists[1:], 1):
                lists.append(values)
                labels.append(f"dense_sub_{index}")
                weights.append(self.config.fusion_weights.get("dense_sub", 1.0))
        for name in ("sparse", "symbol"):
            if name in results:
                lists.append(results[name])
                labels.append(name)
                weights.append(self.config.fusion_weights.get(name, 1.0))
        started = time.perf_counter()
        fused = self.fuser.fuse(lists, self.config.top_k_fused, weights, labels)
        self.last_latencies["fuse"] = round((time.perf_counter() - started) * 1000)
        self.last_trace = {
            "lists": {
                name: [{"id": hit.chunk.id, "score": hit.score, "rank": hit.rank} for hit in values]
                for name, values in results.items()
                if name != "dense"
            },
            "dense": [
                [{"id": hit.chunk.id, "score": hit.score, "rank": hit.rank} for hit in values]
                for values in results.get("dense", [])
            ],
            "fused": self.fuser.last_trace.get("items", []),
            "degraded": self.degraded,
        }
        return fused[:top_k]


RRFusion = WeightedRRF
