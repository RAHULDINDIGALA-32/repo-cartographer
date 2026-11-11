from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass

import structlog

from app.config.pipeline import PipelineConfig
from app.config.settings import Settings
from app.core.errors import AppError, IndexingError, RepoTooLargeError
from app.ingestion.chunkers import AstChunker, FixedChunker
from app.ingestion.enrich import Enricher
from app.ingestion.sync import ChangeSet, ReprocessItem, compute_change_set
from app.ingestion.writer import ChunkVector, IndexWriter
from app.providers.voyage import VoyageEmbedder

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IndexOptions:
    fetch: bool = False
    chunker: str | None = None
    force: bool = False
    no_fetch: bool = False
    allow_pinned: bool = False


class Indexer:
    def __init__(
        self,
        manager,
        settings: Settings,
        config: PipelineConfig | None = None,
        *,
        writer: IndexWriter | None = None,
        embedder=None,
        enricher: Enricher | None = None,
    ):
        self.manager = manager
        self.settings = settings
        self.config = config or PipelineConfig()
        self.writer = writer or IndexWriter(
            manager.store.db, settings, embedding_dim=self.config.embedding_dim
        )
        self.embedder = embedder or VoyageEmbedder(self.config, settings)
        self.enricher = enricher or Enricher(self.config)

    def _chunker(self, override: str | None = None):
        name = override or self.config.chunker
        config = self.config.model_copy(update={"chunker": name})
        kwargs = {
            "config": config,
            "require_exact_tokenizer": self.settings.require_exact_tokenizer,
        }
        if name == "ast":
            return AstChunker(**kwargs)
        if name == "fixed":
            return FixedChunker(config)
        raise IndexingError(f"Unknown chunker: {name}")

    async def _prepare(self, repo_id: int, report, chunker_name: str | None):
        chunker = self._chunker(chunker_name)
        prepared = []
        fallback_counts = Counter()
        symbol_counts = Counter()
        below_min = 0
        started = time.perf_counter()
        for entry in report.entries:
            source = await self.manager.load_source_file(repo_id, entry)
            chunks = await asyncio.to_thread(chunker.chunk, source)
            enriched = [self.enricher.enrich(chunk, source) for chunk in chunks]
            for chunk in enriched:
                if chunk.fallback_reason:
                    fallback_counts[chunk.fallback_reason] += 1
                symbol_counts[chunk.symbol_type] += 1
                below_min += chunk.token_count < self.config.min_chunk_tokens
            prepared.append((entry, enriched))
        return (
            prepared,
            fallback_counts,
            symbol_counts,
            below_min,
            round((time.perf_counter() - started) * 1000),
        )

    async def estimate(self, repo_id: int, *, chunker: str | None = None) -> dict:
        report = await self.manager.scan(repo_id)
        prepared, fallback, symbols, below_min, chunk_ms = await self._prepare(
            repo_id, report, chunker
        )
        chunks = [chunk for _, values in prepared for chunk in values]
        reusable = await self.writer.lookup_embeddings(
            [chunk.content_hash for chunk in chunks if chunk.content_hash], self.embedder.version
        )
        missing = [chunk for chunk in chunks if chunk.content_hash not in reusable]
        tokens = sum(chunk.token_count for chunk in missing)
        max_texts = self.settings.embed_batch_max_texts
        requests = (len(missing) + max_texts - 1) // max_texts
        rpm_time = (
            requests / self.settings.voyage_rpm_limit * 60 if self.settings.voyage_rpm_limit else 0
        )
        tpm_time = (
            tokens / self.settings.voyage_tpm_limit * 60 if self.settings.voyage_tpm_limit else 0
        )
        estimated_seconds = max(rpm_time, tpm_time)
        return {
            "files": len(prepared),
            "chunks": len(chunks),
            "reusable": len(chunks) - len(missing),
            "to_embed": len(missing),
            "embed_tokens": tokens,
            "requests": requests,
            "estimated_seconds": round(estimated_seconds, 2),
            "cap": self.settings.max_chunks_per_repo,
            "cap_warning": len(chunks) > self.settings.max_chunks_per_repo,
            "fallbacks": dict(fallback),
            "symbol_types": dict(symbols),
            "below_min": below_min,
            "chunk_time_ms": chunk_ms,
        }

    async def index_repo(self, repo_id: int, options: IndexOptions | None = None) -> dict:
        options = options or IndexOptions()
        return await self.sync_repo(repo_id, IndexOptions(**{**options.__dict__, "force": True}))

    async def plan(self, repo_id: int, options: IndexOptions | None = None) -> dict:
        """Build a sync plan without database writes or embedding calls."""
        options = options or IndexOptions()
        check = await self.manager.check_remote(repo_id, persist=False)
        existing = await self.writer.load_files(repo_id)
        summaries = await self.writer.load_chunk_summaries(repo_id, chunker_version=self._chunker(options.chunker).version, enricher_version=self.enricher.version, embedder_version=self.embedder.version)
        if not options.force and not check.is_stale:
            return {"status": "up_to_date", "remote_sha": check.remote_sha, "change_set": {"added": 0, "modified": 0, "deleted": 0, "unchanged": len(existing), "reprocess": 0}}
        if not options.no_fetch:
            await self.manager.fetch(repo_id)
        report = await self.manager.scan(repo_id)
        changes = compute_change_set(report.entries, existing, summaries)
        if options.force:
            changes = ChangeSet(changes.added, changes.modified, changes.deleted, changes.unchanged, tuple(ReprocessItem(e.path, ("forced",)) for e in report.entries), changes.renamed_hint)
        counts = await self.writer.chunk_counts(repo_id)
        prepared, fallback, symbols, below_min, chunk_ms = await self._prepare_selected(repo_id, report, changes, options.chunker)
        projected = sum(counts.get(path, 0) for path in {e.path for e in report.entries} - {e.path for e, _ in prepared}) + sum(len(v) for _, v in prepared)
        hashes = [c.content_hash for _, values in prepared for c in values if c.content_hash]
        reusable = await self.writer.lookup_embeddings(hashes, self.embedder.version)
        missing = [c for _, values in prepared for c in values if c.content_hash not in reusable]
        return {"status": "planned", "from_sha": check.indexed_sha, "to_sha": report.head_sha, "change_set": changes.counts, "reprocess_reasons": changes.reason_counts, "renamed_hints": list(changes.renamed_hint), "projected_chunks": projected, "cap": self.settings.max_chunks_per_repo, "cap_warning": projected > self.settings.max_chunks_per_repo, "to_embed": len(missing), "embed_tokens": sum(c.token_count for c in missing), "fallbacks": dict(fallback), "chunk_time_ms": chunk_ms}

    async def _prepare_selected(self, repo_id, report, changes, chunker_name):
        paths = {item.path for item in changes.reprocess}
        selected = report.model_copy(update={"entries": [e for e in report.entries if e.path in paths]})
        return await self._prepare(repo_id, selected, chunker_name)

    async def sync_repo(self, repo_id: int, options: IndexOptions | None = None, *, job_id: int | None = None) -> dict:
        options = options or IndexOptions()
        repo = await self.manager.store.get_repo(repo_id)
        if repo.pinned and not options.allow_pinned:
            raise IndexingError("Repository is pinned; pass --allow-pinned to sync it")
        if not options.force:
            check = await self.manager.check_remote(repo_id, persist=False)
            if not check.is_stale:
                summaries = await self.writer.load_chunk_summaries(repo_id, chunker_version=self._chunker(options.chunker).version, enricher_version=self.enricher.version, embedder_version=self.embedder.version)
                drift = any(v["chunker_drift"] or v["enricher_drift"] or v["embedder_drift"] or v["chunk_count"] == 0 for v in summaries.values())
                if not drift:
                    return {"run_id": None, "status": "up_to_date", "from_sha": repo.indexed_sha, "to_sha": repo.indexed_sha, "duration_ms": 0}
        if job_id is None:
            old_status, old_sha = await self.writer.guard_repo(repo_id, self.settings.index_stale_after_minutes)
        else:
            old_status, old_sha = repo.status, repo.indexed_sha
            await self.writer.mark_indexing(repo_id)
        run_id = None
        counters = Counter()
        stats: dict = {}
        try:
            if options.fetch and not options.no_fetch:
                await self.manager.fetch(repo_id)
            elif not options.no_fetch:
                await self.manager.fetch(repo_id)
            report = await self.manager.scan(repo_id)
            existing_rows = await self.writer.load_files(repo_id)
            summaries = await self.writer.load_chunk_summaries(repo_id, chunker_version=self._chunker(options.chunker).version, enricher_version=self.enricher.version, embedder_version=self.embedder.version)
            changes = compute_change_set(report.entries, existing_rows, summaries)
            if options.force:
                changes = ChangeSet(changes.added, changes.modified, changes.deleted, changes.unchanged, tuple(ReprocessItem(e.path, ("forced",)) for e in report.entries), changes.renamed_hint)
            prepared, fallback, symbols, below_min, chunk_ms = await self._prepare_selected(repo_id, report, changes, options.chunker)
            stats.update(
                skip_reasons={
                    item.reason: {"count": item.count, "bytes": item.total_bytes}
                    for item in report.skipped
                },
                fallback_reasons=dict(fallback),
                symbol_types=dict(symbols),
                below_min=below_min,
                timings_ms={"chunk": chunk_ms},
            )
            existing_counts = await self.writer.chunk_counts(repo_id)
            current_paths = {e.path for e in report.entries}
            processed_paths = {e.path for e, _ in prepared}
            projected = sum(existing_counts.get(path, 0) for path in current_paths - processed_paths) + sum(len(values) for _, values in prepared)
            run_id = await self.writer.start_run(repo_id, old_sha, report.head_sha, self.config.snapshot(), job_id=job_id)
            stats.update(reprocess_reasons=changes.reason_counts, renamed_files=len(changes.renamed_hint), versions={"chunker": self._chunker(options.chunker).version, "enricher": self.enricher.version, "embedder": self.embedder.version}, timings_ms={"chunk": chunk_ms})
            if projected > self.settings.max_chunks_per_repo:
                raise RepoTooLargeError(
                    f"Projected index contains {projected} chunks, exceeding the {self.settings.max_chunks_per_repo} chunk limit"
                )
            all_chunks = [chunk for _, values in prepared for chunk in values]
            reusable = await self.writer.lookup_embeddings(
                [chunk.content_hash for chunk in all_chunks if chunk.content_hash],
                self.embedder.version,
            )
            counters["chunks_reused"] = sum(chunk.content_hash in reusable for chunk in all_chunks)
            counters["chunks_embedded"] = len(all_chunks) - counters["chunks_reused"]
            counters["chunks_created"] = len(all_chunks)
            stats["lookup"] = {"reusable": counters["chunks_reused"]}
            counters["files_added"] = len(changes.added)
            counters["files_modified"] = len(changes.modified)
            counters["files_unchanged"] = len(changes.unchanged)
            embed_tokens = 0
            provider_stats = Counter()
            write_started = time.perf_counter()
            done = 0
            for offset in range(0, len(prepared), self.settings.index_window_files):
                window = prepared[offset : offset + self.settings.index_window_files]
                missing = [
                    chunk
                    for _, values in window
                    for chunk in values
                    if chunk.content_hash not in reusable
                ]
                vectors = (
                    await self.embedder.embed_documents(
                        [chunk.embed_text or chunk.text for chunk in missing]
                    )
                    if missing
                    else []
                )
                for key, value in getattr(self.embedder, "last_accounting", {}).items():
                    provider_stats[key] += value
                vector_iter = iter(vectors)
                for entry, values in window:
                    records = []
                    for chunk in values:
                        vector = (
                            reusable.get(chunk.content_hash)
                            if chunk.content_hash in reusable
                            else next(vector_iter)
                        )
                        if chunk.content_hash not in reusable:
                            embed_tokens += chunk.token_count
                        records.append(ChunkVector(chunk, vector, self.embedder.version))
                    await self.writer.write_file(
                        repo_id, entry, records, run_id, head_sha=report.head_sha
                    )
                    done += 1
                log.info(
                    "index_window_complete",
                    repo_id=repo_id,
                    run_id=run_id,
                    files_done=done,
                    files_total=len(prepared),
                )
            counters["embed_tokens"] = embed_tokens
            stats.update(
                embed_requests=provider_stats["requests"],
                retries=provider_stats["retries"],
                rate_limit_wait_ms=provider_stats["throttle_wait_ms"],
            )
            stats["timings_ms"]["write"] = round((time.perf_counter() - write_started) * 1000)
            counters["chunks_deleted"] = sum(existing_counts.get(path, 0) for path in set(changes.deleted) | processed_paths)
            counters["files_deleted"] = await self.writer.delete_files(repo_id, changes.deleted)
            await self.writer.update_last_seen_sha(repo_id, changes.unchanged, report.head_sha)
            stats["reuse_ratio"] = counters["chunks_reused"] / max(1, counters["chunks_reused"] + counters["chunks_embedded"])
            stats["tokens_saved_estimate"] = sum(c.token_count for c in all_chunks if c.content_hash in reusable)
            await self.writer.finish_run(run_id, "succeeded", counters, stats)
            await self.writer.mark_ready(repo_id, report.head_sha)
            return {
                "run_id": run_id,
                "status": "succeeded",
                **dict(counters),
                "head_sha": report.head_sha,
                "reuse_ratio": stats["reuse_ratio"],
                "tokens_saved_estimate": stats["tokens_saved_estimate"],
            }
        except asyncio.CancelledError:
            if run_id:
                await self.writer.finish_run(run_id, "failed", counters, stats, "cancelled")
            await self.writer.release_repo(
                repo_id, status="ready" if old_status == "ready" else "failed", error="cancelled"
            )
            raise
        except Exception as exc:
            message = str(exc)
            if run_id:
                await self.writer.finish_run(run_id, "failed", counters, stats, message)
            await self.writer.release_repo(
                repo_id, status="ready" if old_status == "ready" else "failed", error=message
            )
            if isinstance(exc, AppError):
                raise
            raise IndexingError(f"Indexing failed: {message}") from exc

    async def _existing_files(self, repo_id: int) -> dict[str, str]:
        async with self.writer.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT path,file_hash FROM {self.writer.schema}.files WHERE repo_id=%s",
                (repo_id,),
            )
            return {row[0]: row[1] for row in await cur.fetchall()}

    async def status(self, repo_id: int) -> dict:
        async with self.writer.db.connection() as conn:
            cur = await conn.execute(
                f"""SELECT r.status,r.indexed_sha,r.indexed_at,r.last_error,
                    (SELECT count(*) FROM {self.writer.schema}.files WHERE repo_id=r.id),
                    (SELECT count(*) FROM {self.writer.schema}.chunks WHERE repo_id=r.id),
                    (SELECT count(*) FROM {self.writer.schema}.chunks WHERE repo_id=r.id AND embedding IS NOT NULL),
                    (SELECT COALESCE(sum(pg_column_size(embedding)+pg_column_size(text)+pg_column_size(search_text)),0)
                     FROM {self.writer.schema}.chunks WHERE repo_id=r.id)
                    FROM {self.writer.schema}.repos r WHERE r.id=%s""",
                (repo_id,),
            )
            row = await cur.fetchone()
            if row is None:
                raise IndexingError("Repository not found")
            return {
                "status": row[0],
                "indexed_sha": row[1],
                "indexed_at": row[2],
                "last_error": row[3],
                "files": row[4],
                "chunks": row[5],
                "embedded": row[6],
                "storage_bytes": row[7],
            }

    async def runs(self, repo_id: int, limit: int = 3) -> list[dict]:
        async with self.writer.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT id,status,files_added,files_modified,files_deleted,files_unchanged,chunks_created,chunks_embedded,chunks_reused,embed_tokens,error,started_at,finished_at,duration_ms,stats FROM {self.writer.schema}.index_runs WHERE repo_id=%s ORDER BY id DESC LIMIT %s",
                (repo_id, limit),
            )
            keys = (
                "id",
                "status",
                "files_added",
                "files_modified",
                "files_deleted",
                "files_unchanged",
                "chunks_created",
                "chunks_embedded",
                "chunks_reused",
                "embed_tokens",
                "error",
                "started_at",
                "finished_at",
                "duration_ms",
                "stats",
            )
            return [dict(zip(keys, row, strict=True)) for row in await cur.fetchall()]

    async def verify(self, repo_id: int, *, allow_drift: bool = False) -> dict:
        async with self.writer.db.connection() as conn:
            checks = {}
            for key, query in {
                "null_embeddings": f"SELECT count(*) FROM {self.writer.schema}.chunks WHERE repo_id=%s AND embedding IS NULL",
                "missing_files": f"SELECT count(*) FROM {self.writer.schema}.chunks c LEFT JOIN {self.writer.schema}.files f ON f.id=c.file_id WHERE c.repo_id=%s AND f.id IS NULL",
                "empty_fts": f"SELECT count(*) FROM {self.writer.schema}.chunks WHERE repo_id=%s AND (fts IS NULL OR fts = ''::tsvector)",
                "empty_search_text": f"SELECT count(*) FROM {self.writer.schema}.chunks WHERE repo_id=%s AND btrim(search_text)=''",
                "invalid_ranges": f"SELECT count(*) FROM {self.writer.schema}.chunks WHERE repo_id=%s AND end_line < start_line",
                "below_min": f"SELECT count(*) FROM {self.writer.schema}.chunks WHERE repo_id=%s AND token_count < %s",
                "empty_files": f"SELECT count(*) FROM (SELECT f.id FROM {self.writer.schema}.files f LEFT JOIN {self.writer.schema}.chunks c ON c.file_id=f.id WHERE f.repo_id=%s GROUP BY f.id HAVING count(c.id)=0) empty_files",
            }.items():
                cur = await conn.execute(
                    query,
                    (repo_id, self.config.min_chunk_tokens) if key == "below_min" else (repo_id,),
                )
                checks[key] = (await cur.fetchone())[0]
            cur = await conn.execute(
                f"SELECT count(*) FROM {self.writer.schema}.chunks WHERE repo_id=%s AND (chunker_version IS NULL OR enricher_version IS NULL OR embedder_version IS NULL)",
                (repo_id,),
            )
            checks["missing_versions"] = (await cur.fetchone())[0]
            cur = await conn.execute(
                f"SELECT count(*) FROM {self.writer.schema}.chunks WHERE repo_id=%s AND embedder_version IS DISTINCT FROM %s",
                (repo_id, self.embedder.version),
            )
            checks["wrong_embedder_version"] = (await cur.fetchone())[0]
            cur = await conn.execute(
                f"SELECT count(DISTINCT chunker_version),count(DISTINCT enricher_version) FROM {self.writer.schema}.chunks WHERE repo_id=%s",
                (repo_id,),
            )
            version_counts = await cur.fetchone()
            checks["chunker_versions"] = version_counts[0]
            checks["enricher_versions"] = version_counts[1]
            active_chunker = self._chunker().version
            active_enricher = self.enricher.version
            cur = await conn.execute(
                f"SELECT count(*) FROM {self.writer.schema}.chunks WHERE repo_id=%s AND chunker_version IS DISTINCT FROM %s",
                (repo_id, active_chunker),
            )
            checks["chunker_drift"] = (await cur.fetchone())[0]
            cur = await conn.execute(
                f"SELECT count(*) FROM {self.writer.schema}.chunks WHERE repo_id=%s AND enricher_version IS DISTINCT FROM %s",
                (repo_id, active_enricher),
            )
            checks["enricher_drift"] = (await cur.fetchone())[0]
            checks["active_chunker_version"] = active_chunker
            checks["active_enricher_version"] = active_enricher
            checks["ok"] = not any(
                checks[key]
                for key in (
                    "null_embeddings",
                    "missing_files",
                    "empty_fts",
                    "empty_search_text",
                    "invalid_ranges",
                    "empty_files",
                    "missing_versions",
                    "wrong_embedder_version",
                    "chunker_drift" if not allow_drift else "never",
                    "enricher_drift" if not allow_drift else "never",
                )
            )
            return checks

    async def reset(self, repo_id: int) -> None:
        async with self.writer.db.transaction() as conn:
            await conn.execute(
                f"DELETE FROM {self.writer.schema}.files WHERE repo_id=%s", (repo_id,)
            )
            await conn.execute(
                f"UPDATE {self.writer.schema}.repos SET status='registered',indexed_sha=NULL,indexed_at=NULL,last_error=NULL,updated_at=now() WHERE id=%s",
                (repo_id,),
            )
