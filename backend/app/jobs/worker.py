from __future__ import annotations

import asyncio
import uuid

import structlog

from app.core.errors import ProviderError, RepoFetchError
from app.ingestion.indexer import IndexOptions
from app.jobs.repository import Job, JobRepository

log = structlog.get_logger(__name__)


class Worker:
    def __init__(self, manager, settings, *, indexer_factory=None, worker_id=None):
        self.manager = manager
        self.settings = settings
        self.jobs = JobRepository(manager.store.db, settings)
        self.worker_id = worker_id or uuid.uuid4().hex
        self.indexer_factory = indexer_factory or (
            lambda: __import__("app.ingestion.indexer", fromlist=["Indexer"]).Indexer(
                manager, settings
            )
        )
        self._stop = asyncio.Event()

    async def run_once(self, options: IndexOptions | None = None) -> Job | None:
        job = await self.jobs.claim_next(self.worker_id)
        if job is None:
            return None
        heartbeat_stop = asyncio.Event()

        async def heartbeat():
            while not heartbeat_stop.is_set():
                try:
                    await asyncio.wait_for(
                        heartbeat_stop.wait(), self.settings.job_heartbeat_seconds
                    )
                except TimeoutError:
                    if not await self.jobs.heartbeat(job.id, self.worker_id):
                        heartbeat_stop.set()
                        return

        task = asyncio.create_task(heartbeat())
        try:
            index_options = options or IndexOptions()
            index_options = IndexOptions(
                fetch=index_options.fetch,
                chunker=index_options.chunker,
                force=index_options.force or job.type == "full_reindex",
                no_fetch=index_options.no_fetch,
                allow_pinned=index_options.allow_pinned or job.trigger == "manual",
            )
            result = await self.indexer_factory().sync_repo(
                job.repo_id,
                index_options,
                job_id=job.id,
            )
            await self.jobs.complete(job.id, result)
        except asyncio.CancelledError:
            await self.jobs.release(job.id)
            raise
        except Exception as exc:
            retryable = isinstance(exc, (ProviderError, RepoFetchError)) and getattr(
                exc, "retryable", True
            )
            code = getattr(exc, "code", "indexing_error")
            await self.jobs.fail(
                job.id,
                code,
                str(exc),
                retryable=retryable,
                retry_after=getattr(exc, "retry_after", None),
            )
        finally:
            heartbeat_stop.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return job

    async def start(self):
        self._stop.clear()
        while not self._stop.is_set():
            await self.jobs.reap_stale(self.settings.job_heartbeat_timeout_seconds)
            job = await self.run_once()
            if job is None:
                await asyncio.sleep(self.settings.worker_poll_seconds)

    async def stop(self, grace: float | None = None):
        self._stop.set()
