import pytest

from app.config.pipeline import PipelineConfig
from app.core.errors import IndexingError
from app.ingestion.writer import ChunkVector, IndexWriter
from app.models import Chunk, FileEntry


async def make_repo(db, schema, name="writer"):
    async with db.transaction() as conn:
        cur = await conn.execute(
            f"INSERT INTO {schema}.repos(url,owner,name,status) VALUES (%s,'test',%s,'registered') RETURNING id",
            (f"https://github.com/test/{name}", name),
        )
        return (await cur.fetchone())[0]


def make_chunk(repo_id, path, line, text):
    return Chunk(
        repo_id=repo_id,
        path=path,
        symbol_type="function",
        symbol="run",
        start_line=line,
        end_line=line,
        text=text,
        token_count=2,
        chunker_version="ast:1",
        content_hash="hash-" + str(line),
        search_text="run " + text,
        enricher_version="enr:1|hdr:on|tok:1",
    )


@pytest.mark.asyncio
async def test_writer_replaces_file_and_reuses_across_repos(test_db):
    settings, db = test_db
    writer = IndexWriter(db, settings)
    repo_id = await make_repo(db, settings.db_schema)
    run_id = await writer.start_run(repo_id, None, "sha", PipelineConfig().snapshot())
    entry = FileEntry(path="a.py", file_hash="file-a", size_bytes=20, language="Python")
    chunk = make_chunk(repo_id, entry.path, 1, "return 1")
    vector = [0.1] * 1024
    await writer.write_file(
        repo_id, entry, [ChunkVector(chunk, vector, "voyage:v:1024")], run_id, head_sha="sha"
    )
    assert "hash-1" in await writer.lookup_embeddings(["hash-1"], "voyage:v:1024")
    await writer.write_file(repo_id, entry, [], run_id, head_sha="sha")
    async with db.connection() as conn:
        cur = await conn.execute(
            f"SELECT count(*) FROM {settings.db_schema}.chunks WHERE repo_id=%s", (repo_id,)
        )
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_writer_rejects_wrong_dimension_without_replacing_old_file(test_db):
    settings, db = test_db
    writer = IndexWriter(db, settings)
    repo_id = await make_repo(db, settings.db_schema, "wrong-dim")
    run_id = await writer.start_run(repo_id, None, "sha", {})
    entry = FileEntry(path="a.py", file_hash="file-a", size_bytes=20, language="Python")
    chunk = make_chunk(repo_id, entry.path, 1, "return 1")
    with pytest.raises(IndexingError):
        await writer.write_file(
            repo_id, entry, [ChunkVector(chunk, [0.1], "voyage:v:1024")], run_id, head_sha="sha"
        )
    async with db.connection() as conn:
        cur = await conn.execute(
            f"SELECT count(*) FROM {settings.db_schema}.files WHERE repo_id=%s", (repo_id,)
        )
        assert (await cur.fetchone())[0] == 0
