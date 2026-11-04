import asyncio
import os
import shutil
from pathlib import Path

import pytest
import pytest_asyncio

from app.config.settings import Settings
from app.db.migrate import MigrationRunner
from app.db.pool import Database


@pytest.fixture(scope="session")
def event_loop_policy():
    if os.name == "nt":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def test_db():
    url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://cartographer:cartographer@localhost:55432/cartographer_test",
    )
    settings = Settings(database_url=url, env="test", data_dir=Path(".test-data"))
    shutil.rmtree(settings.data_dir, ignore_errors=True)
    db = Database(settings)
    await db.open()
    await MigrationRunner(
        db, Path(__file__).parents[1] / "migrations", schema=settings.db_schema, embedding_dim=1024
    ).run()
    async with db.transaction() as conn:
        await conn.execute(f"TRUNCATE {settings.db_schema}.repos RESTART IDENTITY CASCADE")
    try:
        yield settings, db
    finally:
        await db.close()
