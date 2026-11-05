import asyncio

import pytest

from app.config.pipeline import PipelineConfig
from app.core.errors import ProviderError
from app.ingestion.enrich import Enricher
from app.ingestion.tokenizer import split_identifiers
from app.models import SourceFile
from app.providers.gateway import ProviderGateway, ProviderHTTPError
from app.providers.voyage import VoyageEmbedder


def test_identifier_splitter_is_deterministic_and_idempotent():
    value = split_identifiers("HTTPServer parseURLPath snake_case foo-bar.path v2 café")
    assert (
        value
        == "httpserver http server parseurlpath parse url path snake_case snake case foo-bar.path foo bar v2 2 café"
    )
    assert split_identifiers(value) == value


def test_enricher_golden_header_and_hash():
    file = SourceFile(
        repo_id=1,
        path="src/example.py",
        language="Python",
        content="return 1\n",
        file_hash="x",
        size_bytes=9,
    )
    from app.models import Chunk

    chunk = Chunk(
        repo_id=1,
        path=file.path,
        symbol="run",
        symbols=["run"],
        symbol_type="function",
        start_line=4,
        end_line=4,
        text="return 1\n",
        token_count=2,
        chunker_version="ast:1",
    )
    result = Enricher(PipelineConfig()).enrich(chunk, file)
    assert (
        result.embed_text
        == "path: src/example.py\nlanguage: Python\nsymbol: run (function)\nlines: 4-4\n\nreturn 1\n"
    )
    assert result.content_hash and result.search_text
    assert Enricher(PipelineConfig()).enrich(chunk, file) == result


@pytest.mark.asyncio
async def test_gateway_retries_retry_after_and_preserves_secret_hygiene():
    sleeps = []
    calls = 0

    async def sleep(delay):
        sleeps.append(delay)

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProviderHTTPError(429, "rate limited", retry_after=2)
        return "ok"

    gateway = ProviderGateway(max_retries=2, sleep=sleep, random_fn=lambda: 0)
    result = await gateway.execute(
        operation, provider="fake", operation_name="embed", estimated_tokens=4
    )
    assert result.value == "ok"
    assert result.accounting.retries == 1
    assert sleeps == [2]


@pytest.mark.asyncio
async def test_voyage_batches_and_preserves_order():
    calls = []

    async def transport(texts, input_type):
        calls.append((texts, input_type))
        await asyncio.sleep(0)
        return {
            "data": [
                {"index": i, "embedding": [float(len(text))] * 4} for i, text in enumerate(texts)
            ]
        }

    config = PipelineConfig(embedder="fake", embedding_dim=4)
    embedder = VoyageEmbedder(config, gateway=ProviderGateway(max_retries=0), transport=transport)
    values = await embedder.embed_documents(["a", "bb", "ccc"])
    assert [len(value) for value in values] == [4, 4, 4]
    assert [value[0] for value in values] == [1.0, 2.0, 3.0]
    assert all(input_type == "document" for _, input_type in calls)


@pytest.mark.asyncio
async def test_gateway_does_not_retry_client_errors():
    attempts = 0

    async def operation():
        nonlocal attempts
        attempts += 1
        raise ProviderHTTPError(400, "bad request")

    with pytest.raises(ProviderError) as error:
        await ProviderGateway(max_retries=5).execute(
            operation, provider="fake", operation_name="embed"
        )
    assert attempts == 1
    assert error.value.retryable is False
