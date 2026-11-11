# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb

from app.core.errors import ConflictError, NotFoundError


@dataclass(frozen=True)
class Job:
    id: int
    repo_id: int
    type: str
    status: str
    attempts: int
    max_attempts: int
    run_after: Any
    error: str | None = None
    error_code: str | None = None
    trigger: str = "manual"
    worker_id: str | None = None
    result: dict | None = None


@dataclass(frozen=True)
class EnqueueResult:
    job_id: int | None
    created: bool
    reason: str


class JobRepository:
    def __init__(self, db, settings):
        self.db = db
        self.schema = settings.db_schema
        self.settings = settings

    def _columns(self):
        return "id,repo_id,type,status,attempts,max_attempts,run_after,error,error_code,trigger,worker_id,result"

    @staticmethod
    def _job(row) -> Job:
        return Job(*row)

    async def enqueue(
        self, repo_id: int, job_type: str = "sync", trigger: str = "manual", *, run_after=None
    ) -> EnqueueResult:
        if job_type not in {"sync", "full_reindex"}:
            raise ValueError("unknown job type")
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"SELECT id,type FROM {self.schema}.jobs WHERE repo_id=%s AND status='pending' ORDER BY CASE WHEN type='full_reindex' THEN 0 ELSE 1 END,id LIMIT 1",
                (repo_id,),
            )
            pending = await cur.fetchone()
            if pending and (pending[1] == "full_reindex" or job_type == "sync"):
                return EnqueueResult(pending[0], False, "coalesced")
            cur = await conn.execute(
                f"INSERT INTO {self.schema}.jobs(repo_id,type,status,run_after,trigger,max_attempts) VALUES (%s,%s,'pending',COALESCE(%s,now()),%s,%s) RETURNING id",
                (repo_id, job_type, run_after, trigger, self.settings.job_max_attempts),
            )
            return EnqueueResult((await cur.fetchone())[0], True, "created")

    async def claim_next(self, worker_id: str) -> Job | None:
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"""SELECT {self._columns()} FROM {self.schema}.jobs j
                WHERE j.status='pending' AND j.run_after <= now()
                  AND NOT EXISTS (SELECT 1 FROM {self.schema}.jobs r WHERE r.repo_id=j.repo_id AND r.status='running')
                ORDER BY j.run_after,j.created_at,j.id FOR UPDATE SKIP LOCKED LIMIT 1"""
            )
            row = await cur.fetchone()
            if row is None:
                return None
            if row[2] == "full_reindex":
                await conn.execute(
                    f"UPDATE {self.schema}.jobs SET status='done',result=%s,finished_at=now() WHERE repo_id=%s AND type='sync' AND status='pending'",
                    (Jsonb({"status": "superseded", "by": row[0]}), row[1]),
                )
            cur = await conn.execute(
                f"UPDATE {self.schema}.jobs SET status='running',started_at=now(),heartbeat_at=now(),worker_id=%s,attempts=attempts+1 WHERE id=%s RETURNING {self._columns()}",
                (worker_id, row[0]),
            )
            return self._job(await cur.fetchone())

    async def heartbeat(self, job_id: int, worker_id: str) -> bool:
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"UPDATE {self.schema}.jobs SET heartbeat_at=now() WHERE id=%s AND status='running' AND worker_id=%s",
                (job_id, worker_id),
            )
            return cur.rowcount == 1

    async def complete(self, job_id: int, result: dict) -> None:
        async with self.db.transaction() as conn:
            await conn.execute(
                f"UPDATE {self.schema}.jobs SET status='done',result=%s,finished_at=now() WHERE id=%s AND status='running'",
                (Jsonb(result), job_id),
            )

    async def fail(
        self,
        job_id: int,
        error_code: str,
        error: str,
        *,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> str:
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"SELECT attempts,max_attempts FROM {self.schema}.jobs WHERE id=%s FOR UPDATE",
                (job_id,),
            )
            row = await cur.fetchone()
            if row is None:
                raise NotFoundError("Job not found")
            retry = retryable and row[0] < row[1]
            if retry:
                delay = (
                    retry_after
                    if retry_after is not None
                    else min(
                        self.settings.job_backoff_max_seconds,
                        self.settings.job_backoff_base_seconds * (2 ** max(0, row[0] - 1)),
                    )
                )
                await conn.execute(
                    f"UPDATE {self.schema}.jobs SET status='pending',run_after=now()+(%s * interval '1 second'),error_code=%s,error=%s,worker_id=NULL WHERE id=%s",
                    (delay, error_code, error[:2000], job_id),
                )
                return "pending"
            await conn.execute(
                f"UPDATE {self.schema}.jobs SET status='failed',error_code=%s,error=%s,finished_at=now() WHERE id=%s",
                (error_code, error[:2000], job_id),
            )
            return "failed"

    async def release(self, job_id: int) -> None:
        async with self.db.transaction() as conn:
            await conn.execute(
                f"UPDATE {self.schema}.jobs SET status='pending',worker_id=NULL,heartbeat_at=NULL WHERE id=%s AND status='running'",
                (job_id,),
            )

    async def reap_stale(self, timeout_seconds: float) -> int:
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"UPDATE {self.schema}.jobs SET status=CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'pending' END,error_code='worker_lost',error='heartbeat expired',finished_at=CASE WHEN attempts >= max_attempts THEN now() ELSE NULL END,worker_id=NULL WHERE status='running' AND heartbeat_at < now()-(%s * interval '1 second')",
                (timeout_seconds,),
            )
            await conn.execute(
                f"""UPDATE {self.schema}.repos
                SET status=CASE WHEN indexed_sha IS NULL THEN 'registered' ELSE 'ready' END,
                    updated_at=now()
                WHERE status='indexing'
                  AND NOT EXISTS (SELECT 1 FROM {self.schema}.jobs
                                  WHERE repo_id=repos.id AND status='running')"""
            )
            return cur.rowcount

    async def get(self, job_id: int) -> Job:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT {self._columns()} FROM {self.schema}.jobs WHERE id=%s", (job_id,)
            )
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError("Job not found")
        return self._job(row)

    async def list(self, *, repo_id=None, status=None, limit=20) -> list[Job]:
        clauses, params = [], []
        if repo_id is not None:
            clauses.append("repo_id=%s")
            params.append(repo_id)
        if status is not None:
            clauses.append("status=%s")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        async with self.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT {self._columns()} FROM {self.schema}.jobs{where} ORDER BY id DESC LIMIT %s",
                (*params, limit),
            )
            return [self._job(row) for row in await cur.fetchall()]

    async def cancel(self, job_id: int) -> None:
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"UPDATE {self.schema}.jobs SET status='failed',error_code='cancelled',error='cancelled by operator',finished_at=now() WHERE id=%s AND status='pending'",
                (job_id,),
            )
            if cur.rowcount == 0:
                raise ConflictError("Only pending jobs can be cancelled")

    async def retry(self, job_id: int) -> EnqueueResult:
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"UPDATE {self.schema}.jobs SET status='pending',run_after=now(),error=NULL,error_code=NULL,finished_at=NULL WHERE id=%s AND status='failed' RETURNING id",
                (job_id,),
            )
            if cur.rowcount == 0:
                raise ConflictError("Only failed jobs can be retried")
            return EnqueueResult(job_id, True, "retried")

    async def prune(self, days: int) -> int:
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"DELETE FROM {self.schema}.jobs WHERE status IN ('done','failed') AND finished_at < now()-(%s * interval '1 day')",
                (days,),
            )
            return cur.rowcount
