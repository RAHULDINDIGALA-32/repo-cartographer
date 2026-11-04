import pytest

from app.models import SourceFile
from tests.fakes import FakeChunker, FakeEmbedder


@pytest.mark.asyncio
async def test_fakes_are_deterministic():
    file = SourceFile(repo_id=1, path="a.py", content="one\ntwo", file_hash="x", size_bytes=7)
    assert FakeChunker().chunk(file)[1].start_line == 2
    embedder = FakeEmbedder(4)
    assert await embedder.embed_query("x") == await embedder.embed_query("x")
