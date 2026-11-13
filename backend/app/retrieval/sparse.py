from __future__ import annotations

import re

from app.ingestion.tokenizer import split_identifiers
from app.models import ChunkRecord, QueryAnalysis, RetrievalHit

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "does",
    "do",
    "for",
    "from",
    "how",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "where",
    "which",
    "who",
    "why",
    "with",
    "in",
    "this",
    "that",
    "there",
    "when",
    "was",
}


def query_tokens(analysis: QueryAnalysis, limit: int = 24) -> list[str]:
    values = [*analysis.identifiers, *analysis.keywords, analysis.rewritten_query]
    result: list[str] = []
    for value in values:
        for token in split_identifiers(value).split():
            if len(token) <= 1 or token in STOP_WORDS or not re.fullmatch(r"[\w-]+", token):
                continue
            if token not in result:
                result.append(token)
            if len(result) >= limit:
                return result
    return result


def _hit(row, rank: int, source: str = "sparse") -> RetrievalHit:
    chunk = ChunkRecord(
        id=row[0],
        file_id=row[1],
        repo_id=row[2],
        path=row[3],
        symbol=row[4],
        symbol_type=row[5],
        parent_symbol=row[6],
        start_line=row[7],
        end_line=row[8],
        text=row[9],
        content_hash=row[10],
        search_text=row[11],
        token_count=row[12],
        chunker_version=row[13],
        enricher_version=row[14],
        embedder_version=row[15],
    )
    return RetrievalHit(chunk=chunk, score=float(row[16]), rank=rank, source=source)


class SparseRetriever:
    name = "sparse"
    version = "sparse:1"

    def __init__(self, db=None, settings=None, **_: object):
        self.db = db
        self.schema = settings.db_schema if settings is not None else "cartographer"
        self.last_trace: dict = {}
        self.last_indexed_sha: str | None = None
        self.last_status: str | None = None

    async def retrieve(
        self,
        repo_id: int,
        analysis: QueryAnalysis,
        top_k: int,
        *,
        path_prefix: str | None = None,
        language: str | None = None,
        **_,
    ) -> list[RetrievalHit]:
        tokens = query_tokens(analysis)
        if not tokens:
            self.last_trace = {"tokens": []}
            return []
        tsquery = " | ".join(f"{token}:*" for token in tokens)
        filters = ["c.repo_id=%s", "c.fts @@ query.q"]
        params: list[object] = [tsquery, repo_id]
        if path_prefix:
            filters.append("f.path LIKE %s")
            params.append(path_prefix.rstrip("/") + "/%")
        if language:
            filters.append("lower(f.language)=lower(%s)")
            params.append(language)
        params.append(max(0, int(top_k)))
        sql = f"""WITH query AS (SELECT to_tsquery('simple', %s) AS q)
            SELECT c.id,c.file_id,c.repo_id,f.path,c.symbol,c.symbol_type,c.parent_symbol,
                   c.start_line,c.end_line,c.text,c.content_hash,c.search_text,c.token_count,
                   c.chunker_version,c.enricher_version,c.embedder_version,
                   ts_rank_cd(c.fts, query.q, 32) AS score
            FROM {self.schema}.chunks c
            JOIN {self.schema}.files f ON f.id=c.file_id CROSS JOIN query
            WHERE {" AND ".join(filters)}
            ORDER BY score DESC,c.id ASC LIMIT %s"""
        async with self.db.connection() as conn:
            cur = await conn.execute(sql, params)
            rows = await cur.fetchall()
            state = await conn.execute(
                f"SELECT status,indexed_sha FROM {self.schema}.repos WHERE id=%s", (repo_id,)
            )
            state_row = await state.fetchone()
        if state_row is None:
            from app.core.errors import NotFoundError

            raise NotFoundError("Repository not found")
        self.last_status, self.last_indexed_sha = state_row
        hits = [_hit(row, rank) for rank, row in enumerate(rows, 1)]
        self.last_trace = {
            "tokens": tokens,
            "ids": [hit.chunk.id for hit in hits],
            "path_prefix": path_prefix,
            "language": language,
        }
        return hits


class SymbolRetriever:
    name = "symbol"
    version = "symbol:1"

    def __init__(self, db=None, settings=None, **_: object):
        self.db = db
        self.schema = settings.db_schema if settings is not None else "cartographer"
        self.last_trace: dict = {}
        self.last_indexed_sha: str | None = None
        self.last_status: str | None = None

    async def retrieve(
        self,
        repo_id: int,
        analysis: QueryAnalysis,
        top_k: int,
        *,
        path_prefix: str | None = None,
        language: str | None = None,
        **_,
    ) -> list[RetrievalHit]:
        identifiers = [value for value in analysis.identifiers if value]
        if not identifiers:
            return []
        values = [value.lower() for value in identifiers]
        filters = [
            "c.repo_id=%s",
            "(lower(c.symbol)=ANY(%s) OR lower(c.parent_symbol)=ANY(%s))",
        ]
        params: list[object] = [values, repo_id, values, values]
        if path_prefix:
            filters.append("f.path LIKE %s")
            params.append(path_prefix.rstrip("/") + "/%")
        if language:
            filters.append("lower(f.language)=lower(%s)")
            params.append(language)
        params.append(max(0, int(top_k)))
        sql = f"""SELECT c.id,c.file_id,c.repo_id,f.path,c.symbol,c.symbol_type,c.parent_symbol,
                   c.start_line,c.end_line,c.text,c.content_hash,c.search_text,c.token_count,
                   c.chunker_version,c.enricher_version,c.embedder_version,
                   CASE WHEN lower(c.symbol) = ANY(%s) THEN 2.0 ELSE 1.0 END AS score
            FROM {self.schema}.chunks c JOIN {self.schema}.files f ON f.id=c.file_id
            WHERE {" AND ".join(filters)}
            ORDER BY score DESC,
                     CASE WHEN c.symbol_type IN ('function','method','class') THEN 0 ELSE 1 END,
                     c.id ASC LIMIT %s"""
        async with self.db.connection() as conn:
            cur = await conn.execute(sql, params)
            rows = await cur.fetchall()
            state = await conn.execute(
                f"SELECT status,indexed_sha FROM {self.schema}.repos WHERE id=%s", (repo_id,)
            )
            state_row = await state.fetchone()
        if state_row is None:
            from app.core.errors import NotFoundError

            raise NotFoundError("Repository not found")
        self.last_status, self.last_indexed_sha = state_row
        hits = [_hit(row, rank, "symbol") for rank, row in enumerate(rows, 1)]
        self.last_trace = {"identifiers": identifiers, "ids": [hit.chunk.id for hit in hits]}
        return hits
