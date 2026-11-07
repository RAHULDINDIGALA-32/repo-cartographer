from types import SimpleNamespace

import pytest

from app.config.pipeline import LLMSpec, PipelineConfig
from app.providers.anthropic import ClaudeGenerator
from app.providers.errors import classify_provider_error
from app.providers.gateway import ProviderGateway
from app.providers.openai_compatible import OpenAICompatibleGenerator
from app.providers.profiles import get_profile
from app.retrieval.dense import DenseRetriever


class AsyncEvents:
    def __init__(self, events):
        self.events = events

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.events:
            raise StopAsyncIteration
        return self.events.pop(0)


class FakeOpenAI:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        assert kwargs["stream"] is True
        return AsyncEvents(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="answer ["), finish_reason=None
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(reasoning_content="hidden"), finish_reason=None
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="1]"), finish_reason="stop")
                    ],
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2),
                ),
            ]
        )


class FakeAnthropicStream:
    def __init__(self):
        self.events = AsyncEvents(
            [
                SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(text="OK [1]")),
            ]
        )

    def __aiter__(self):
        return self.events

    def get_final_message(self):
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=8, output_tokens=3), stop_reason="end_turn"
        )


class FakeAnthropicContext:
    async def __aenter__(self):
        return FakeAnthropicStream()

    async def __aexit__(self, *args):
        return False


class FakeAnthropic:
    def __init__(self):
        self.messages = SimpleNamespace(stream=lambda **kwargs: FakeAnthropicContext())


@pytest.mark.asyncio
async def test_openai_compatible_stream_filters_reasoning_and_reports_usage():
    config = PipelineConfig(generator=LLMSpec(provider="groq", model="test-model", max_tokens=10))
    generator = OpenAICompatibleGenerator(
        config=config,
        client=FakeOpenAI(),
        profile=get_profile("groq"),
        gateway=ProviderGateway(max_retries=0),
    )
    events = [event async for event in generator.stream("q", [], [])]
    assert "".join(event.text or "" for event in events if event.kind == "token") == "answer [1]"
    assert events[-1].stats["usage_source"] == "api"
    assert events[-1].stats["tokens_in"] == 10


@pytest.mark.asyncio
async def test_anthropic_stream_uses_llm_spec_and_reports_usage():
    config = PipelineConfig(
        generator=LLMSpec(provider="anthropic", model="test-model", max_tokens=10)
    )
    generator = ClaudeGenerator(
        config=config,
        client=FakeAnthropic(),
        profile=get_profile("anthropic"),
        gateway=ProviderGateway(max_retries=0),
    )
    events = [event async for event in generator.stream("q", [], [])]
    assert events[0].text == "OK [1]"
    assert events[-1].stats["tokens_out"] == 3


def test_llm_snapshot_is_secret_free_and_old_shape_is_rejected():
    config = PipelineConfig(
        generator=LLMSpec(provider="openrouter", model="vendor/model", max_tokens=8)
    )
    snapshot = str(config.snapshot())
    assert "api_key" not in snapshot
    with pytest.raises(ValueError, match="Deprecated LLM keys"):
        PipelineConfig(generator_model="secret-model")


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "provider_auth", False),
        (402, "provider_billing", False),
        (404, "provider_model_not_found", False),
        (400, "provider_bad_request", False),
        (429, "provider_rate_limited", True),
        (503, "provider_overloaded", True),
    ],
)
def test_provider_error_taxonomy(status, code, retryable):
    failure = classify_provider_error(Exception(f"HTTP {status}"), status)
    assert (failure.code, failure.retryable) == (code, retryable)


@pytest.mark.asyncio
async def test_dense_retrieval_repo_cte_exposes_id_for_lateral_filter():
    class Cursor:
        async def fetchall(self):
            return [("ready", "sha", None)]

    class Connection:
        def __init__(self):
            self.sql = None

        async def execute(self, sql, params):
            self.sql = sql
            return Cursor()

    class ConnectionContext:
        def __init__(self, connection):
            self.connection_value = connection

        async def __aenter__(self):
            return self.connection_value

        async def __aexit__(self, *args):
            return False

    class Database:
        def __init__(self):
            self.connection_value = Connection()

        def connection(self):
            return ConnectionContext(self.connection_value)

    retriever = DenseRetriever(db=Database())
    retriever.embedder = SimpleNamespace(dimension=2)
    await retriever.retrieve_vector(1, [0.1, 0.2], "voyage-code-3", 1)
    assert "SELECT id,status,indexed_sha" in retriever.last_sql
    assert "c.repo_id=r.id" in retriever.last_sql
