import os

import pytest

from app.config.pipeline import PipelineConfig
from app.config.settings import Settings
from app.providers.voyage import VoyageEmbedder


@pytest.mark.network
@pytest.mark.asyncio
async def test_live_voyage_embedding():
    if not os.getenv("VOYAGE_API_KEY"):
        pytest.skip("VOYAGE_API_KEY is not configured")
    settings = Settings(
        database_url="postgresql://unused/unused",
        voyage_api_key=os.environ["VOYAGE_API_KEY"],
    )
    embedder = VoyageEmbedder(PipelineConfig(), settings)
    vectors = await embedder.embed_documents(
        ["def alpha(): pass", "class Beta: pass", "return alpha()"]
    )
    assert len(vectors) == 3
    assert all(len(vector) == 1024 for vector in vectors)
    assert all(abs(sum(value * value for value in vector) ** 0.5 - 1) < 0.02 for vector in vectors)
