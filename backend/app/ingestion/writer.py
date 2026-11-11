from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from app.core.errors import ConflictError, IndexingError, NotFoundError
from app.models import Chunk, FileEntry


@dataclass(frozen=True)
class ChunkVector:
    chunk: Chunk
    vector: list[float] | None
    embedder_version: str | None = None


class IndexWriter:
    def __init__(self, db, settings, *, embedding_dim: int = 1024):
        self.db = db
        self.settings = settings
        self.schema = settings.db_schema
        self.embedding_dim = embedding_dim

    async def start_run(
        self, repo_id: int, from_sha: str | None, to_sha: str, config_snapshot: dict, *, job_id: int | None = None
    ) -> int:
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"INSERT INTO {self.schema}.index_runs(repo_id,job_id,from_sha,to_sha,status,config_snapshot) "
                "VALUES (%s,%s,%s,%s,'running',%s) RETURNING id",
                (repo_id, job_id, from_sha, to_sha, Jsonb(config_snapshot)),
            )
            return (await cur.fetchone())[0]

    @staticmethod
    def _parts(
        value: ChunkVector
        | tuple[Chunk, list[float] | None]
        | tuple[Chunk, list[float] | None, str],
    ) -> ChunkVector:
        return value if isinstance(value, ChunkVector) else ChunkVector(*value)

    async def write_file(
        self,
        repo_id: int,
        file_entry: FileEntry,
        chunks_with_vectors: Iterable[
            ChunkVector | tuple[Chunk, list[float] | None] | tuple[Chunk, list[float] | None, str]
        ],
        run_id: int,
        *,
        head_sha: str,
    ) -> int:
        values = [self._parts(value) for value in chunks_with_vectors]
        try:
            async with self.db.transaction() as conn:
                cur = await conn.execute(
                    f"INSERT INTO {self.schema}.files(repo_id,path,file_hash,language,size_bytes,last_seen_sha) "
                    "VALUES (%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT(repo_id,path) DO UPDATE SET file_hash=EXCLUDED.file_hash,language=EXCLUDED.language,"
                    "size_bytes=EXCLUDED.size_bytes,last_seen_sha=EXCLUDED.last_seen_sha RETURNING id",
                    (
                        repo_id,
                        file_entry.path,
                        file_entry.file_hash,
                        file_entry.language,
                        file_entry.size_bytes,
                        head_sha,
                    ),
                )
                file_id = (await cur.fetchone())[0]
                await conn.execute(f"DELETE FROM {self.schema}.chunks WHERE file_id=%s", (file_id,))
                rows = []
                for value in values:
                    chunk = value.chunk
                    if value.vector is not None and len(value.vector) != self.embedding_dim:
                        raise IndexingError(f"Wrong embedding dimension for {file_entry.path}")
                    rows.append(
                        (
                            repo_id,
                            file_id,
                            chunk.symbol,
                            chunk.symbol_type,
                            chunk.parent_symbol,
                            chunk.start_line,
                            chunk.end_line,
                            chunk.text,
                            chunk.content_hash or "",
                            chunk.search_text or "",
                            chunk.token_count,
                            chunk.chunker_version,
                            chunk.enricher_version or "",
                            value.embedder_version,
                            value.vector,
                        )
                    )
                if rows:
                    async with conn.cursor() as cursor:
                        await cursor.executemany(
                            f"INSERT INTO {self.schema}.chunks(repo_id,file_id,symbol,symbol_type,parent_symbol,start_line,end_line,text,content_hash,search_text,token_count,chunker_version,enricher_version,embedder_version,embedding) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            rows,
                        )
                return len(rows)
        except IndexingError:
            raise
        except Exception as exc:
            raise IndexingError(f"Failed to write indexed file {file_entry.path}") from exc

    async def delete_files(self, repo_id: int, paths: Iterable[str]) -> int:
        paths = list(paths)
        if not paths:
            return 0
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"DELETE FROM {self.schema}.files WHERE repo_id=%s AND path = ANY(%s)",
                (repo_id, paths),
            )
            return cur.rowcount

    async def lookup_embeddings(
        self, content_hashes: Iterable[str], embedder_version: str
    ) -> dict[str, list[float]]:
        hashes = list(dict.fromkeys(content_hashes))
        if not hashes:
            return {}
        async with self.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT content_hash,embedding FROM {self.schema}.chunks WHERE content_hash = ANY(%s) AND embedder_version=%s AND embedding IS NOT NULL",
                (hashes, embedder_version),
            )
            from app.retrieval.vectors import vector_to_list

            return {
                row[0]: vector_to_list(row[1], dimension=self.embedding_dim)
                for row in await cur.fetchall()
            }

    async def load_files(self, repo_id: int) -> list[dict]:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT id,path,file_hash,language,size_bytes,last_seen_sha FROM {self.schema}.files WHERE repo_id=%s ORDER BY path",
                (repo_id,),
            )
            return [dict(zip(("id", "path", "file_hash", "language", "size_bytes", "last_seen_sha"), row, strict=True)) for row in await cur.fetchall()]

    async def load_chunk_summaries(self, repo_id: int, *, chunker_version: str, enricher_version: str, embedder_version: str) -> dict[str, dict]:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                f"""SELECT f.path, count(c.id),
                    bool_or(c.chunker_version IS DISTINCT FROM %s),
                    bool_or(c.enricher_version IS DISTINCT FROM %s),
                    bool_or(c.embedder_version IS DISTINCT FROM %s)
                    FROM {self.schema}.files f LEFT JOIN {self.schema}.chunks c ON c.file_id=f.id
                    WHERE f.repo_id=%s GROUP BY f.path ORDER BY f.path""",
                (chunker_version, enricher_version, embedder_version, repo_id),
            )
            return {row[0]: {"chunk_count": row[1], "chunker_drift": bool(row[2] or False), "enricher_drift": bool(row[3] or False), "embedder_drift": bool(row[4] or False)} for row in await cur.fetchall()}

    async def chunk_counts(self, repo_id: int) -> dict[str, int]:
        async with self.db.connection() as conn:
            cur = await conn.execute(f"SELECT f.path,count(c.id) FROM {self.schema}.files f LEFT JOIN {self.schema}.chunks c ON c.file_id=f.id WHERE f.repo_id=%s GROUP BY f.path", (repo_id,))
            return {row[0]: row[1] for row in await cur.fetchall()}

    async def update_last_seen_sha(self, repo_id: int, paths: Iterable[str], sha: str) -> int:
        paths = list(paths)
        if not paths:
            return 0
        async with self.db.transaction() as conn:
            cur = await conn.execute(f"UPDATE {self.schema}.files SET last_seen_sha=%s WHERE repo_id=%s AND path=ANY(%s)", (sha, repo_id, paths))
            return cur.rowcount

    async def repo_pinned(self, repo_id: int) -> bool:
        async with self.db.connection() as conn:
            cur = await conn.execute(f"SELECT pinned FROM {self.schema}.repos WHERE id=%s", (repo_id,))
            row = await cur.fetchone()
            if row is None:
                raise NotFoundError("Repository not found")
            return bool(row[0])

    async def finish_run(
        self, run_id: int, status: str, counters: dict, stats: dict, error: str | None = None
    ) -> None:
        allowed = {
            "files_added",
            "files_modified",
            "files_deleted",
            "files_unchanged",
            "chunks_created",
            "chunks_embedded",
            "chunks_reused",
            "chunks_deleted",
            "embed_tokens",
        }
        values = {key: int(counters.get(key, 0)) for key in allowed}
        values.update(
            embed_requests=int(stats.get("embed_requests", 0)),
            rate_limit_wait_ms=int(stats.get("rate_limit_wait_ms", 0)),
        )
        assignments = ",".join(f"{key}=%s" for key in values)
        async with self.db.transaction() as conn:
            await conn.execute(
                f"UPDATE {self.schema}.index_runs SET status=%s,error=%s,stats=%s,{assignments},finished_at=now(),duration_ms=(EXTRACT(EPOCH FROM (now()-started_at))*1000)::integer WHERE id=%s",
                (status, error, Jsonb(stats), *values.values(), run_id),
            )

    async def guard_repo(
        self, repo_id: int, stale_after_minutes: int
    ) -> tuple[str | None, str | None]:
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"SELECT status,indexed_sha FROM {self.schema}.repos WHERE id=%s FOR UPDATE",
                (repo_id,),
            )
            row = await cur.fetchone()
            if row is None:
                raise NotFoundError("Repository not found")
            if row[0] == "indexing":
                cur = await conn.execute(
                    f"SELECT started_at FROM {self.schema}.index_runs WHERE repo_id=%s AND status='running' ORDER BY started_at DESC LIMIT 1",
                    (repo_id,),
                )
                running = await cur.fetchone()
                if (
                    running
                    and (datetime.now(UTC) - running[0]).total_seconds() < stale_after_minutes * 60
                ):
                    raise ConflictError("Repository is already being indexed")
            await conn.execute(
                f"UPDATE {self.schema}.repos SET status='indexing',last_error=NULL,updated_at=now() WHERE id=%s",
                (repo_id,),
            )
            return row[0], row[1]

    async def release_repo(self, repo_id: int, *, status: str, error: str | None = None) -> None:
        async with self.db.transaction() as conn:
            await conn.execute(
                f"UPDATE {self.schema}.repos SET status=%s,last_error=%s,updated_at=now() WHERE id=%s",
                (status, error, repo_id),
            )

    async def mark_ready(self, repo_id: int, head_sha: str) -> None:
        async with self.db.transaction() as conn:
            await conn.execute(
                f"UPDATE {self.schema}.repos SET status='ready',indexed_sha=%s,indexed_at=now(),last_error=NULL,updated_at=now() WHERE id=%s",
                (head_sha, repo_id),
            )

    async def mark_indexing(self, repo_id: int) -> None:
        async with self.db.transaction() as conn:
            await conn.execute(f"UPDATE {self.schema}.repos SET status='indexing',last_error=NULL,updated_at=now() WHERE id=%s", (repo_id,))
