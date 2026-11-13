from pydantic import ValidationError

from app.api.limiter import TokenBucketLimiter
from app.api.models import AskOptions, AskRequest
from app.config.settings import Settings
from app.models import ChunkRecord, RetrievalHit


def test_production_settings_require_admin_key_and_reject_wildcard():
    try:
        Settings(
            database_url="postgresql://localhost/db",
            env="prod",
            cors_origins=["*"],
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("production settings must reject missing admin keys and wildcard CORS")


def test_api_models_reject_unknown_fields():
    try:
        AskRequest(question="hello", unexpected=True)
    except ValidationError:
        pass
    else:
        raise AssertionError("API request models must be strict")


def test_swagger_placeholder_filters_are_treated_as_omitted():
    options = AskOptions(path_prefix="string", language=" string ")
    assert options.path_prefix is None
    assert options.language is None


def test_bm25_is_a_valid_retrieval_source():
    chunk = ChunkRecord(
        id=1,
        file_id=1,
        repo_id=1,
        path="a.py",
        symbol_type="function",
        start_line=1,
        end_line=2,
        text="return 1",
        token_count=2,
        chunker_version="ast:1",
    )
    assert RetrievalHit(chunk=chunk, score=1.0, source="bm25", rank=1).source == "bm25"


def test_token_bucket_burst_and_refill():
    now = [0.0]
    limiter = TokenBucketLimiter(rate_per_minute=60, burst=2, clock=lambda: now[0])

    async def run():
        assert await limiter.allow("a")
        assert await limiter.allow("a")
        assert not await limiter.allow("a")
        now[0] = 1.0
        assert await limiter.allow("a")

    import asyncio

    asyncio.run(run())


def test_zero_wait_ask_reserves_available_slot(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import app.api.routes as routes

    async def no_budget(*_args):
        return None

    monkeypatch.setattr(routes, "_ask_budget", no_budget)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                ask_slots=asyncio.Semaphore(1),
                active_asks=0,
                settings=SimpleNamespace(ask_queue_wait_ms=0),
            )
        ),
        state=SimpleNamespace(),
    )

    async def run():
        await routes._reserve_ask(request, "test")
        assert request.state.ask_slot_acquired is True
        assert request.app.state.active_asks == 1
        routes._release_ask(request)
        assert request.app.state.active_asks == 0

    asyncio.run(run())
