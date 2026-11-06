from __future__ import annotations

from app.core.errors import ConflictError, NotFoundError, RetrievalError
from app.models import ChunkRecord, QueryAnalysis, RetrievalHit
from app.retrieval.vectors import vector_to_list


class DenseRetriever:
    name = "dense"
    version = "dense:1"

    def __init__(self, db=None, settings=None, config=None, embedder=None, **_: object):
        self.db = db
        self.settings = settings
        self.config = config
        self.embedder = embedder
        self.schema = settings.db_schema if settings is not None else "cartographer"
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
    ) -> list[RetrievalHit]:
        if self.embedder is None:
            raise RetrievalError("Dense retriever requires an embedder")
        query_vector = await self.embedder.embed_query(analysis.rewritten_query)
        dimension = getattr(self.embedder, "dimension", None)
        query_vector = vector_to_list(query_vector, dimension=dimension)
        embedder_version = self.embedder.version
        async with self.db.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    f"SELECT status,indexed_sha FROM {self.schema}.repos WHERE id=%s", (repo_id,)
                )
                repo = await cur.fetchone()
                if repo is None:
                    raise NotFoundError("Repository not found")
                self.last_status, self.last_indexed_sha = repo
                if repo[0] != "ready":
                    raise ConflictError("Repository is not ready for querying")
                conditions = [
                    "c.repo_id=%s",
                    "c.embedder_version=%s",
                    "c.embedding IS NOT NULL",
                ]
                params: list[object] = [repo_id, embedder_version]
                if path_prefix:
                    conditions.append("f.path LIKE %s")
                    params.append(path_prefix.rstrip("/") + "/%")
                if language:
                    conditions.append("lower(f.language)=lower(%s)")
                    params.append(language)
                params = [query_vector, *params, max(0, int(top_k))]
                cur = await conn.execute(
                    f"""SELECT c.id,c.file_id,c.symbol,c.symbol_type,c.parent_symbol,c.start_line,c.end_line,c.text,
                    c.content_hash,c.search_text,c.token_count,c.chunker_version,c.enricher_version,
                    c.embedder_version,c.embedding,f.path,f.language,c.embedding <=> %s AS distance
                    FROM {self.schema}.chunks c JOIN {self.schema}.files f ON f.id=c.file_id
                    WHERE {" AND ".join(conditions)}
                    ORDER BY distance ASC,c.id ASC LIMIT %s""",
                    params,
                )
                rows = await cur.fetchall()
        hits = []
        for rank, row in enumerate(rows, 1):
            chunk = ChunkRecord(
                id=row[0],
                file_id=row[1],
                repo_id=repo_id,
                path=row[15],
                symbol=row[2],
                symbol_type=row[3],
                parent_symbol=row[4],
                start_line=row[5],
                end_line=row[6],
                text=row[7],
                content_hash=row[8],
                search_text=row[9],
                token_count=row[10],
                chunker_version=row[11],
                enricher_version=row[12],
                embedder_version=row[13],
            )
            hits.append(
                RetrievalHit(
                    chunk=chunk, score=max(-1.0, 1.0 - float(row[17])), rank=rank, source="dense"
                )
            )
        return hits
