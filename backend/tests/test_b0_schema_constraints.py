import pytest
from psycopg import errors


async def repo_id(db, schema):
    async with db.transaction() as conn:
        cur = await conn.execute(
            f"INSERT INTO {schema}.repos(url,owner,name,status) VALUES ('https://github.com/a/b','a','b','registered') RETURNING id"
        )
        return (await cur.fetchone())[0]


@pytest.mark.asyncio
async def test_files_unique(test_db):
    s, db = test_db
    rid = await repo_id(db, s.db_schema)
    async with db.transaction() as conn:
        await conn.execute(
            f"INSERT INTO {s.db_schema}.files(repo_id,path,file_hash,size_bytes,last_seen_sha) VALUES (%s,'a.py','x',1,'s')",
            (rid,),
        )
        with pytest.raises(errors.UniqueViolation):
            await conn.execute(
                f"INSERT INTO {s.db_schema}.files(repo_id,path,file_hash,size_bytes,last_seen_sha) VALUES (%s,'a.py','y',1,'s')",
                (rid,),
            )


@pytest.mark.asyncio
async def test_repo_delete_cascades(test_db):
    s, db = test_db
    rid = await repo_id(db, s.db_schema)
    async with db.transaction() as conn:
        await conn.execute(
            f"INSERT INTO {s.db_schema}.files(repo_id,path,file_hash,size_bytes,last_seen_sha) VALUES (%s,'a.py','x',1,'s')",
            (rid,),
        )
        await conn.execute(
            f"INSERT INTO {s.db_schema}.jobs(repo_id,type,status) VALUES (%s,'sync','pending')",
            (rid,),
        )
        await conn.execute(
            f"INSERT INTO {s.db_schema}.index_runs(repo_id,to_sha,status) VALUES (%s,'s','succeeded')",
            (rid,),
        )
        await conn.execute(
            f"INSERT INTO {s.db_schema}.query_logs(repo_id,query) VALUES (%s,'q')", (rid,)
        )
        await conn.execute(f"DELETE FROM {s.db_schema}.repos WHERE id=%s", (rid,))
        cur = await conn.execute(
            f"SELECT count(*) FROM {s.db_schema}.files WHERE repo_id=%s", (rid,)
        )
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_job_partial_uniques(test_db):
    s, db = test_db
    rid = await repo_id(db, s.db_schema)
    async with db.transaction() as conn:
        await conn.execute(
            f"INSERT INTO {s.db_schema}.jobs(repo_id,type,status) VALUES (%s,'sync','pending')",
            (rid,),
        )
        with pytest.raises(errors.UniqueViolation):
            async with conn.transaction():
                await conn.execute(
                    f"INSERT INTO {s.db_schema}.jobs(repo_id,type,status) VALUES (%s,'sync','pending')",
                    (rid,),
                )
        await conn.execute(
            f"INSERT INTO {s.db_schema}.jobs(repo_id,type,status) VALUES (%s,'full_reindex','running')",
            (rid,),
        )
        with pytest.raises(errors.UniqueViolation):
            async with conn.transaction():
                await conn.execute(
                    f"INSERT INTO {s.db_schema}.jobs(repo_id,type,status) VALUES (%s,'sync','running')",
                    (rid,),
                )


@pytest.mark.asyncio
async def test_chunk_checks(test_db):
    s, db = test_db
    rid = await repo_id(db, s.db_schema)
    async with db.transaction() as conn:
        cur = await conn.execute(
            f"INSERT INTO {s.db_schema}.files(repo_id,path,file_hash,size_bytes,last_seen_sha) VALUES (%s,'a.py','x',1,'s') RETURNING id",
            (rid,),
        )
        fid = (await cur.fetchone())[0]
        with pytest.raises(errors.CheckViolation):
            await conn.execute(
                f"INSERT INTO {s.db_schema}.chunks(repo_id,file_id,symbol_type,start_line,end_line,text,content_hash,search_text,token_count,chunker_version) VALUES (%s,%s,'bad',2,1,'x','x','x',1,'x')",
                (rid, fid),
            )


@pytest.mark.asyncio
async def test_vector_dimension(test_db):
    s, db = test_db
    rid = await repo_id(db, s.db_schema)
    async with db.transaction() as conn:
        cur = await conn.execute(
            f"INSERT INTO {s.db_schema}.files(repo_id,path,file_hash,size_bytes,last_seen_sha) VALUES (%s,'a.py','x',1,'s') RETURNING id",
            (rid,),
        )
        fid = (await cur.fetchone())[0]
        with pytest.raises(Exception):
            await conn.execute(
                f"INSERT INTO {s.db_schema}.chunks(repo_id,file_id,symbol_type,start_line,end_line,text,content_hash,search_text,token_count,chunker_version,embedding) VALUES (%s,%s,'function',1,1,'x','x','x',1,'x',%s)",
                (rid, fid, [1.0]),
            )


@pytest.mark.asyncio
async def test_fts_generated(test_db):
    s, db = test_db
    rid = await repo_id(db, s.db_schema)
    async with db.transaction() as conn:
        cur = await conn.execute(
            f"INSERT INTO {s.db_schema}.files(repo_id,path,file_hash,size_bytes,last_seen_sha) VALUES (%s,'a.py','x',1,'s') RETURNING id",
            (rid,),
        )
        fid = (await cur.fetchone())[0]
        await conn.execute(
            f"INSERT INTO {s.db_schema}.chunks(repo_id,file_id,symbol_type,start_line,end_line,text,content_hash,search_text,token_count,chunker_version) VALUES (%s,%s,'function',1,1,'x','x','verify token',1,'x')",
            (rid, fid),
        )
        cur = await conn.execute(
            f"SELECT count(*) FROM {s.db_schema}.chunks WHERE fts @@ plainto_tsquery('simple','verify')"
        )
        assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_feedback_rating(test_db):
    s, db = test_db
    rid = await repo_id(db, s.db_schema)
    async with db.transaction() as conn:
        cur = await conn.execute(
            f"INSERT INTO {s.db_schema}.query_logs(repo_id,query) VALUES (%s,'q') RETURNING id",
            (rid,),
        )
        qid = (await cur.fetchone())[0]
        with pytest.raises(errors.CheckViolation):
            await conn.execute(
                f"INSERT INTO {s.db_schema}.feedback(query_log_id,rating) VALUES (%s,0)", (qid,)
            )


@pytest.mark.asyncio
async def test_migrations_are_idempotent(test_db):
    s, db = test_db
    from app.db.migrate import MigrationRunner

    runner = MigrationRunner(
        db, __import__("pathlib").Path("migrations"), schema=s.db_schema, embedding_dim=1024
    )
    assert await runner.run() == []
    assert (await runner.status())["pending"] == []
