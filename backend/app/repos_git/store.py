from __future__ import annotations

from datetime import UTC, datetime

from psycopg import errors

from app.core.errors import ConflictError, DatabaseError, NotFoundError, RepoTooLargeError
from app.models import Repo, RepoRef


class RepoStore:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings
        self.schema = settings.db_schema

    def _select(self, suffix: str) -> str:
        return (
            f"SELECT id,url,owner,name,default_branch,indexed_sha,status,last_error,"
            f"last_checked_at,last_queried_at,indexed_at,created_at,updated_at,pinned FROM "
            f"{self.schema}.repos {suffix}"
        )

    async def _row(self, cursor) -> Repo | None:
        row = await cursor.fetchone()
        if row is None:
            return None
        return Repo(
            id=row[0],
            ref=RepoRef(owner=row[2], name=row[3], url=row[1]),
            default_branch=row[4],
            indexed_sha=row[5],
            status=row[6],
            last_error=row[7],
            last_checked_at=row[8],
            last_queried_at=row[9],
            indexed_at=row[10],
            created_at=row[11],
            updated_at=row[12],
            pinned=row[13],
        )

    async def get_repo(self, repo_id: int) -> Repo:
        async with self.db.connection() as conn:
            cur = await conn.execute(self._select("WHERE id=%s"), (repo_id,))
            repo = await self._row(cur)
        if repo is None:
            raise NotFoundError("Repository not found")
        return repo

    async def get_repo_by_url(self, url: str) -> Repo | None:
        async with self.db.connection() as conn:
            cur = await conn.execute(self._select("WHERE url=%s"), (url,))
            return await self._row(cur)

    async def list_repos(self) -> list[Repo]:
        async with self.db.connection() as conn:
            cur = await conn.execute(self._select("ORDER BY id"))
            return [
                r
                for row in await cur.fetchall()
                for r in [
                    Repo(
                        id=row[0],
                        ref=RepoRef(owner=row[2], name=row[3], url=row[1]),
                        default_branch=row[4],
                        indexed_sha=row[5],
                        status=row[6],
                        last_error=row[7],
                        last_checked_at=row[8],
                        last_queried_at=row[9],
                        indexed_at=row[10],
                        created_at=row[11],
                        updated_at=row[12],
                        pinned=row[13],
                    )
                ]
            ]

    async def count_repos(self) -> int:
        async with self.db.connection() as conn:
            cur = await conn.execute(f"SELECT count(*) FROM {self.schema}.repos")
            return (await cur.fetchone())[0]

    async def create_repo(self, ref: RepoRef, default_branch: str) -> Repo:
        async with self.db.transaction() as conn:
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"repo-cap:{self.schema}",)
            )
            cur = await conn.execute(f"SELECT count(*) FROM {self.schema}.repos")
            if (await cur.fetchone())[0] >= self.settings.max_repos:
                raise RepoTooLargeError(
                    "Repository limit reached",
                    details={"cap": "max_repos", "limit": self.settings.max_repos},
                )
            try:
                await conn.execute(
                    f"INSERT INTO {self.schema}.repos(url,owner,name,default_branch,status,"
                    "last_checked_at) VALUES (%s,%s,%s,%s,'registered',now())",
                    (ref.url, ref.owner, ref.name, default_branch),
                )
            except errors.UniqueViolation as exc:
                raise ConflictError("Repository is already registered") from exc
        return await self.get_repo_by_url(ref.url)

    async def update_repo_fields(self, repo_id: int, **fields):
        allowed = {
            "default_branch",
            "status",
            "last_error",
            "last_checked_at",
            "indexed_at",
            "indexed_sha",
            "updated_at",
            "pinned",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise DatabaseError(f"Unsupported repository fields: {sorted(unknown)}")
        fields["updated_at"] = datetime.now(UTC)
        assignments = ",".join(f"{key}=%s" for key in fields)
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"UPDATE {self.schema}.repos SET {assignments} WHERE id=%s",
                (*fields.values(), repo_id),
            )
            if cur.rowcount == 0:
                raise NotFoundError("Repository not found")
        return await self.get_repo(repo_id)

    async def delete_repo(self, repo_id: int) -> int:
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"SELECT count(*) FROM {self.schema}.repos WHERE id=%s", (repo_id,)
            )
            if (await cur.fetchone())[0] == 0:
                raise NotFoundError("Repository not found")
            cur = await conn.execute(f"DELETE FROM {self.schema}.repos WHERE id=%s", (repo_id,))
            return cur.rowcount
