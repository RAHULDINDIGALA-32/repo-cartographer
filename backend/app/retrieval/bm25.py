from __future__ import annotations

import math
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass

from app.retrieval.sparse import _hit, query_tokens


@dataclass
class _Index:
    rows: list[tuple]
    terms: list[list[str]]
    postings: dict[str, dict[int, int]]
    lengths: list[int]
    avg_length: float
    fingerprint: tuple[int, int | None]
    loaded_at: float


class BM25Retriever:
    name = "bm25"
    version = "bm25:1"

    def __init__(self, db=None, settings=None, config=None, **_: object):
        self.db = db
        self.schema = settings.db_schema if settings is not None else "cartographer"
        self.settings = settings
        self.config = config
        self.cache: OrderedDict[int, _Index] = OrderedDict()
        self.last_trace = {}
        self._last_cache_hit = False
        self.last_indexed_sha = None
        self.last_status = None

    async def _load(self, repo_id: int) -> _Index:
        now = time.monotonic()
        cached = self.cache.get(repo_id)
        async with self.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT count(*),max(id) FROM {self.schema}.chunks WHERE repo_id=%s", (repo_id,)
            )
            fingerprint = await cur.fetchone()
        ttl = getattr(self.settings, "bm25_cache_ttl_seconds", 30)
        max_repositories = getattr(self.settings, "bm25_cache_repositories", 3)
        cache_hit = bool(
            cached
            and cached.fingerprint == tuple(fingerprint)
            and now - cached.loaded_at < ttl
        )
        if cache_hit:
            self._last_cache_hit = True
            self.cache.move_to_end(repo_id)
            return cached
        async with self.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT c.id,c.file_id,c.repo_id,f.path,c.symbol,c.symbol_type,c.parent_symbol,c.start_line,c.end_line,c.text,c.content_hash,c.search_text,c.token_count,c.chunker_version,c.enricher_version,c.embedder_version,0.0 FROM {self.schema}.chunks c JOIN {self.schema}.files f ON f.id=c.file_id WHERE c.repo_id=%s ORDER BY c.id",
                (repo_id,),
            )
            rows = await cur.fetchall()
            state = await conn.execute(
                f"SELECT status,indexed_sha FROM {self.schema}.repos WHERE id=%s", (repo_id,)
            )
            state_row = await state.fetchone()
        self.last_status, self.last_indexed_sha = state_row or (None, None)
        terms = [row[11].lower().split() for row in rows]
        postings: dict[str, dict[int, int]] = {}
        for index, values in enumerate(terms):
            for term, count in Counter(values).items():
                postings.setdefault(term, {})[index] = count
        value = _Index(
            rows,
            terms,
            postings,
            [len(v) for v in terms],
            sum(map(len, terms)) / max(1, len(terms)),
            tuple(fingerprint),
            now,
        )
        self.cache[repo_id] = value
        self._last_cache_hit = False
        self.cache.move_to_end(repo_id)
        while len(self.cache) > max_repositories:
            self.cache.popitem(last=False)
        return value

    async def retrieve(self, repo_id: int, analysis, top_k: int, **_) -> list:
        tokens = query_tokens(analysis)
        if not tokens:
            return []
        index = await self._load(repo_id)
        n = len(index.rows)
        scores: dict[int, float] = {}
        k1 = getattr(self.config, "bm25_k1", 1.2)
        b = getattr(self.config, "bm25_b", 0.75)
        query_terms = set(tokens)
        for term in query_terms:
            posting = index.postings.get(term, {})
            idf = max(0.0, math.log(1 + (n - len(posting) + 0.5) / (len(posting) + 0.5)))
            for doc, frequency in posting.items():
                denominator = frequency + k1 * (
                    1 - b + b * index.lengths[doc] / max(1, index.avg_length)
                )
                scores[doc] = scores.get(doc, 0.0) + idf * frequency * (k1 + 1) / denominator
        ordered = sorted(scores, key=lambda doc: (-scores[doc], index.rows[doc][0]))[
            : max(0, int(top_k))
        ]
        hits = [
            _hit(index.rows[doc][:16] + (scores[doc],), rank, "bm25")
            for rank, doc in enumerate(ordered, 1)
        ]
        self.last_trace = {
            "tokens": tokens,
            "ids": [hit.chunk.id for hit in hits],
            "cache": "hit" if self._last_cache_hit else "miss",
        }
        return hits
