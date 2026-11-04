from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from app.config.settings import Settings
from app.core.errors import DatabaseError
from app.models import HealthStatus


class Database:
    def __init__(
        self, settings: Settings, *, url: str | None = None, embedding_dim: int | None = None
    ):
        self.settings = settings
        self.embedding_dim = embedding_dim
        self.url = url or settings.database_url
        self.pool: AsyncConnectionPool | None = None

    async def open(self):
        self.pool = AsyncConnectionPool(
            self.url,
            min_size=self.settings.db_pool_min,
            max_size=self.settings.db_pool_max,
            open=False,
            kwargs={"prepare_threshold": None},
            configure=self._configure,
        )
        await self.pool.open(wait=True)

    async def _configure(self, conn: AsyncConnection):
        await register_vector_async(conn)

    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection]:
        if self.pool is None:
            raise DatabaseError("Database pool is not open")
        async with self.pool.connection() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        async with self.connection() as conn:
            async with conn.transaction():
                yield conn

    async def health(self) -> HealthStatus:
        try:
            async with self.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
                    await cur.execute(
                        f"SELECT max(version) FROM {self.settings.db_schema}.schema_migrations"
                    )
                    version = (await cur.fetchone())[0]
                    await cur.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
                    )
                    extensions_ok = (await cur.fetchone())[0]
                    await cur.execute(
                        f"SELECT value FROM {self.settings.db_schema}.schema_meta "
                        "WHERE key='embedding_dim'"
                    )
                    value = (await cur.fetchone())[0]
                    match = int(value) == self._embedding_dim()
                    return HealthStatus(
                        ok=extensions_ok and match,
                        migration_version=version,
                        extensions_ok=extensions_ok,
                        embedding_dim_match=match,
                        details={"schema": self.settings.db_schema},
                    )
        except Exception as exc:
            raise DatabaseError(f"Database health check failed: {exc}") from exc

    def _embedding_dim(self):
        if self.embedding_dim is not None:
            return self.embedding_dim
        from app.config.pipeline import PipelineConfig

        return PipelineConfig().embedding_dim
