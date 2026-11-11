# ruff: noqa: E501

from __future__ import annotations

from app.core.errors import ConflictError, NotFoundError
from app.jobs.repository import EnqueueResult, JobRepository


class RepoService:
    automatic_triggers = {"scheduler", "lazy_check", "webhook"}

    def __init__(self, db, settings):
        self.db = db
        self.settings = settings
        self.schema = settings.db_schema
        self.jobs = JobRepository(db, settings)

    async def enqueue_sync(
        self,
        repo_id: int,
        trigger: str = "manual",
        *,
        force: bool = False,
        override_pin: bool = False,
    ) -> EnqueueResult:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT status,pinned FROM {self.schema}.repos WHERE id=%s", (repo_id,)
            )
            repo = await cur.fetchone()
        if repo is None:
            raise NotFoundError("Repository not found")
        if repo[1] and not override_pin:
            raise ConflictError("Repository is pinned")
        if repo[0] == "indexing":
            raise ConflictError("Repository is already indexing")
        if trigger in self.automatic_triggers:
            async with self.db.connection() as conn:
                cur = await conn.execute(
                    f"SELECT COALESCE(sum(embed_tokens),0),count(*) FROM {self.schema}.index_runs WHERE repo_id=%s AND started_at >= now()-interval '1 day'",
                    (repo_id,),
                )
                tokens, runs = await cur.fetchone()
                cur = await conn.execute(
                    f"SELECT COALESCE(sum(embed_tokens),0) FROM {self.schema}.index_runs WHERE started_at >= now()-interval '1 day'",
                    (),
                )
                total = (await cur.fetchone())[0]
            if (
                runs >= self.settings.auto_sync_max_per_repo_per_day
                or total >= self.settings.auto_sync_daily_token_budget
            ):
                return EnqueueResult(None, False, "budget_exhausted")
        return await self.jobs.enqueue(repo_id, "full_reindex" if force else "sync", trigger)
