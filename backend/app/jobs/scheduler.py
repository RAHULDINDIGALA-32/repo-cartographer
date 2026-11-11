from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta

import structlog

from app.jobs.service import RepoService

log = structlog.get_logger(__name__)


class Scheduler:
    def __init__(self, manager, settings, *, service=None):
        self.manager = manager
        self.settings = settings
        self.service = service or RepoService(manager.store.db, settings)
        self._stop = asyncio.Event()

    async def tick(self, *, dry_run: bool = False) -> dict:
        repos = await self.manager.store.list_repos()
        checked = enqueued = skipped = 0
        details = []
        for repo in repos:
            if checked >= self.settings.scheduler_max_checks_per_tick:
                skipped += 1
                details.append({"repo_id": repo.id, "reason": "tick_cap"})
                continue
            if repo.pinned or repo.status == "indexing":
                skipped += 1
                details.append(
                    {"repo_id": repo.id, "reason": "pinned" if repo.pinned else "indexing"}
                )
                continue
            if repo.status == "registered" and repo.indexed_sha is None:
                skipped += 1
                details.append({"repo_id": repo.id, "reason": "not_indexed"})
                continue
            if repo.last_checked_at is not None:
                age = await self._age_seconds(repo.last_checked_at)
                interval = await self._interval_seconds(repo)
                if age < interval:
                    skipped += 1
                    details.append(
                        {
                            "repo_id": repo.id,
                            "reason": "cadence",
                            "next_due_at": (repo.last_checked_at + timedelta(seconds=interval)),
                        }
                    )
                    continue
            checked += 1
            if dry_run:
                details.append({"repo_id": repo.id, "reason": "would_check"})
                continue
            try:
                result = await self.manager.check_remote(repo.id)
                item = {
                    "repo_id": repo.id,
                    "remote_sha": result.remote_sha,
                    "stale": result.is_stale,
                }
                if result.is_stale and not dry_run:
                    queued = await self.service.enqueue_sync(repo.id, "scheduler")
                    item["enqueue"] = queued.reason
                    enqueued += int(queued.created)
                details.append(item)
            except Exception as exc:
                details.append({"repo_id": repo.id, "error": str(exc)[:200]})
        return {"checked": checked, "enqueued": enqueued, "skipped": skipped, "details": details}

    async def _interval_seconds(self, repo) -> float:
        if repo.last_queried_at is not None:
            query_age = await self._age_seconds(repo.last_queried_at)
        else:
            query_age = float("inf")
        if query_age <= self.settings.active_window_hours * 3600:
            return self.settings.poll_interval_active_minutes * 60
        age = await self._age_seconds(repo.last_checked_at)
        if age <= self.settings.idle_after_days * 86400:
            return self.settings.poll_interval_normal_minutes * 60
        return self.settings.poll_interval_idle_minutes * 60

    async def status(self) -> dict:
        repos = await self.manager.store.list_repos()
        rows = []
        now = datetime.now(UTC)
        for repo in repos:
            if repo.pinned:
                due = None
                reason = "pinned"
            elif repo.status == "registered" and repo.indexed_sha is None:
                due = None
                reason = "not_indexed"
            elif repo.last_checked_at is None:
                due = now
                reason = "never_checked"
            else:
                interval = await self._interval_seconds(repo)
                due = repo.last_checked_at + timedelta(seconds=interval)
                reason = "due" if due <= now else "cadence"
            rows.append(
                {
                    "repo_id": repo.id,
                    "status": repo.status,
                    "pinned": repo.pinned,
                    "next_due_at": due,
                    "reason": reason,
                }
            )
        async with self.manager.store.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT count(*),coalesce(sum((result->>'embed_tokens')::bigint),0) "
                f"FROM {self.manager.store.schema}.jobs WHERE status='done' "
                "AND finished_at >= now()-interval '1 day'"
            )
            runs, tokens = await cur.fetchone()
        return {
            "budget": {
                "runs_24h": runs,
                "tokens_24h": tokens,
                "token_limit": self.settings.auto_sync_daily_token_budget,
            },
            "repos": rows,
        }

    async def _age_seconds(self, timestamp):
        async with self.manager.store.db.connection() as conn:
            cur = await conn.execute("SELECT EXTRACT(EPOCH FROM (now()-%s))", (timestamp,))
            return float((await cur.fetchone())[0])

    async def start(self):
        self._stop.clear()
        while not self._stop.is_set():
            await self.tick()
            await asyncio.sleep(
                self.settings.scheduler_tick_seconds
                + random.uniform(0, max(0.1, self.settings.scheduler_tick_seconds * 0.1))
            )

    async def stop(self, grace: float | None = None):
        self._stop.set()
