from __future__ import annotations

from pgvector import Vector

from app.core.errors import ConflictError, NotFoundError, RetrievalError
from app.models import ChunkRecord, QueryAnalysis, RetrievalHit
from app.retrieval.vectors import vector_to_list


class DenseRetriever:
    name = "dense"
    version = "dense:2"

    def __init__(self, db=None, settings=None, config=None, embedder=None, **_: object):
        self.db = db
        self.settings = settings
        self.config = config
        self.embedder = embedder
        self.schema = settings.db_schema if settings is not None else "cartographer"
        self.last_indexed_sha: str | None = None
        self.last_status: str | None = None
        self.last_sql: str | None = None
        self.last_params: list[object] | None = None

    async def retrieve(
        self,
        repo_id: int,
        analysis: QueryAnalysis,
        top_k: int,
        *,
        path_prefix: str | None = None,
        language: str | None = None,
    ) -> list[RetrievalHit]:
        if self.embedder is None:
            raise RetrievalError("Dense retriever requires an embedder")
        query_vector = await self.embedder.embed_query(analysis.rewritten_query)
        return await self.retrieve_vector(
            repo_id,
            query_vector,
            self.embedder.version,
            top_k,
            path_prefix=path_prefix,
            language=language,
        )

    async def retrieve_vector(
        self,
        repo_id: int,
        query_vector,
        embedder_version: str,
        top_k: int,
        *,
        path_prefix: str | None = None,
        language: str | None = None,
    ) -> list[RetrievalHit]:
        query_vector = vector_to_list(
            query_vector, dimension=getattr(self.embedder, "dimension", None)
        )
        conditions = ["c.embedder_version=%s", "c.embedding IS NOT NULL"]
        params: list[object] = [repo_id, Vector(query_vector), embedder_version]
        if path_prefix:
            conditions.append("f.path LIKE %s")
            params.append(path_prefix.rstrip("/") + "/%")
        if language:
            conditions.append("lower(f.language)=lower(%s)")
            params.append(language)
        params.append(max(0, int(top_k)))
        sql = f"""WITH repo AS (
            SELECT id,status,indexed_sha FROM {self.schema}.repos WHERE id=%s
        )
        SELECT r.status,r.indexed_sha,q.id,q.file_id,q.symbol,q.symbol_type,q.parent_symbol,
               q.start_line,q.end_line,q.text,q.content_hash,q.search_text,q.token_count,
               q.chunker_version,q.enricher_version,q.embedder_version,q.path,q.language,q.distance
        FROM repo r
        LEFT JOIN LATERAL (
            SELECT c.id,c.file_id,c.symbol,c.symbol_type,c.parent_symbol,c.start_line,c.end_line,
                   c.text,c.content_hash,c.search_text,c.token_count,c.chunker_version,
                   c.enricher_version,c.embedder_version,f.path,f.language,c.embedding <=> %s AS distance
            FROM {self.schema}.chunks c
            JOIN {self.schema}.files f ON f.id=c.file_id
            WHERE c.repo_id=r.id AND {" AND ".join(conditions)}
            ORDER BY distance ASC,c.id ASC LIMIT %s
        ) q ON TRUE"""
        self.last_sql = sql
        self.last_params = params
        async with self.db.connection() as conn:
            cur = await conn.execute(sql, params)
            rows = await cur.fetchall()
        if not rows:
            raise NotFoundError("Repository not found")
        self.last_status, self.last_indexed_sha = rows[0][0], rows[0][1]
        if self.last_status != "ready":
            raise ConflictError("Repository is not ready for querying")
        hits = []
        for rank, row in enumerate((row for row in rows if row[2] is not None), 1):
            chunk = ChunkRecord(
                id=row[2],
                file_id=row[3],
                repo_id=repo_id,
                path=row[16],
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
            hits.append(
                RetrievalHit(
                    chunk=chunk, score=max(-1.0, 1.0 - float(row[18])), rank=rank, source="dense"
                )
            )
        return hits
