from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.models import AskRequest, FeedbackRequest, RepoCreateRequest, SyncRequest
from app.api.security import client_identity, request_id, require_admin
from app.core.errors import (
    AppError,
    BudgetExhaustedError,
    ConflictError,
    NotFoundError,
    RateLimitedError,
    RepoNotReadyError,
    ServerBusyError,
)
from app.generation.engine import QueryEngine, QueryOptions
from app.jobs.repository import JobRepository
from app.jobs.service import RepoService

router = APIRouter(prefix="/v1")


def _error(request: Request, exc: AppError, *, status: int | None = None):
    retryable = bool(getattr(exc, "retryable", False)) or (status or exc.http_status) in {429, 503}
    body = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "retryable": retryable,
            "request_id": request_id(request),
        }
    }
    if exc.details:
        body["error"]["details"] = exc.details
    response = JSONResponse(body, status_code=status or exc.http_status)
    if response.status_code in {429, 503}:
        response.headers["Retry-After"] = str(max(1, int(getattr(exc, "retry_after", 1))))
    return response


async def _repo(request: Request, repo_id: int):
    try:
        return await request.app.state.manager.store.get_repo(repo_id)
    except AppError:
        raise


async def _rate_limit(request: Request, kind: str):
    identity = client_identity(request, request.app.state.settings.trusted_proxy_count)
    limiter = request.app.state.ask_limiter if kind == "ask" else request.app.state.write_limiter
    if not await limiter.allow(identity):
        raise RateLimitedError("Rate limit exceeded")
    return identity


async def _ask_budget(request: Request, identity: str):
    settings = request.app.state.settings
    schema = settings.db_schema
    async with request.app.state.db.connection() as conn:
        cur = await conn.execute(
            f"SELECT coalesce(sum(coalesce(tokens_out,0)),0),count(*) FROM {schema}.query_logs "
            "WHERE created_at >= current_date"
        )
        total, count = await cur.fetchone()
    if count >= settings.ask_daily_per_client:
        raise RateLimitedError("Daily ask limit exceeded")
    if total >= settings.ask_daily_token_budget:
        raise BudgetExhaustedError("Daily generation-token budget exhausted")


def _sse_frame(number: int, kind: str, payload: dict) -> str:
    data = json.dumps(payload, default=str, separators=(",", ":"))
    return f"id: {number}\nevent: {kind}\ndata: {data}\n\n"


@router.get("/repos")
async def list_repos(request: Request):
    repos = await request.app.state.manager.store.list_repos()
    return [
        {
            "id": repo.id,
            "url": repo.ref.url,
            "default_branch": repo.default_branch,
            "status": repo.status,
            "indexed_sha": repo.indexed_sha,
            "indexed_at": repo.indexed_at,
            "pinned": repo.pinned,
            "remote_sha": repo.remote_sha,
            "remote_checked_at": repo.remote_checked_at,
            "staleness": None
            if repo.remote_sha is None or repo.indexed_sha is None
            else repo.remote_sha != repo.indexed_sha,
        }
        for repo in repos
    ]


@router.get("/repos/{repo_id}")
async def get_repo(request: Request, repo_id: int):
    repo = await _repo(request, repo_id)
    runs = await request.app.state.indexer.runs(repo_id, 5)
    return {"repo": repo.model_dump(mode="json"), "runs": runs}


@router.post("/repos")
async def add_repo(request: Request, body: RepoCreateRequest, _: str = Depends(require_admin)):
    registration = await request.app.state.manager.register(body.url)
    result = {
        "repo": registration.repo.model_dump(mode="json"),
        "already_existed": registration.already_existed,
    }
    if body.enqueue:
        result["enqueue"] = (
            await RepoService(request.app.state.db, request.app.state.settings).enqueue_sync(
                registration.repo.id, "api"
            )
        ).__dict__
    return result


@router.delete("/repos/{repo_id}")
async def delete_repo(
    request: Request, repo_id: int, override_pin: bool = False, _: str = Depends(require_admin)
):
    repo = await _repo(request, repo_id)
    if repo.pinned and not override_pin:
        raise ConflictError("Repository is pinned")
    await request.app.state.manager.remove(repo_id)
    return {"deleted": True, "repo_id": repo_id}


@router.post("/repos/{repo_id}/sync")
async def sync_repo(
    request: Request, repo_id: int, body: SyncRequest, _: str = Depends(require_admin)
):
    result = await RepoService(request.app.state.db, request.app.state.settings).enqueue_sync(
        repo_id, "api", force=body.force, override_pin=body.override_pin
    )
    return result.__dict__


@router.get("/repos/{repo_id}/jobs")
async def repo_jobs(request: Request, repo_id: int, _: str = Depends(require_admin)):
    await _repo(request, repo_id)
    return [
        asdict(job)
        for job in await JobRepository(request.app.state.db, request.app.state.settings).list(
            repo_id=repo_id
        )
    ]


async def _ask_events(request: Request, repo_id: int, body: AskRequest, identity: str):
    options = body.options
    query_options = QueryOptions(
        top_k=options.k if options else None,
        path_prefix=options.path_prefix if options else None,
        language=options.language if options else None,
    )
    engine = QueryEngine(
        request.app.state.db, request.app.state.settings, request.app.state.pipeline
    )
    async for event in engine.ask(repo_id, body.question, query_options):
        yield event


async def _reserve_ask(request: Request, identity: str):
    await _ask_budget(request, identity)
    slots = request.app.state.ask_slots
    if slots.locked() and request.app.state.settings.ask_queue_wait_ms == 0:
        raise ServerBusyError("Ask concurrency limit reached")
    try:
        await asyncio.wait_for(
            slots.acquire(), request.app.state.settings.ask_queue_wait_ms / 1000
        )
    except TimeoutError as exc:
        raise ServerBusyError("Ask concurrency limit reached") from exc


@router.post("/repos/{repo_id}/ask")
async def ask(request: Request, repo_id: int, body: AskRequest):
    repo = await _repo(request, repo_id)
    if repo.status != "ready":
        raise RepoNotReadyError("Repository is not indexed and ready for questions")
    identity = await _rate_limit(request, "ask")
    await _reserve_ask(request, identity)
    if body.stream:

        async def stream():
            number = 0
            iterator = _ask_events(request, repo_id, body, identity).__aiter__()
            current = None
            deadline = time.monotonic() + request.app.state.settings.ask_timeout_seconds
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    if current is None:
                        current = asyncio.create_task(iterator.__anext__())
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    done, _ = await asyncio.wait(
                        {current},
                        timeout=min(remaining, request.app.state.settings.sse_heartbeat_seconds),
                    )
                    if not done:
                        yield ": ping\n\n"
                        continue
                    try:
                        event = current.result()
                    except StopAsyncIteration:
                        return
                    current = None
                    number += 1
                    yield _sse_frame(number, event.get("kind", "status"), event)
            except AppError as exc:
                number += 1
                yield _sse_frame(number, "error", {"code": exc.code, "message": exc.message})
            except TimeoutError:
                number += 1
                yield _sse_frame(
                    number, "error", {"code": "provider_timeout", "message": "Ask timed out"}
                )
            finally:
                if current:
                    current.cancel()
                    await asyncio.gather(current, return_exceptions=True)
                await iterator.aclose()
                request.app.state.ask_slots.release()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Request-ID": request_id(request),
            },
        )
    events = []
    try:
        async for event in _ask_events(request, repo_id, body, identity):
            events.append(event)
    except TimeoutError as exc:
        raise AppError("Ask timed out") from exc
    finally:
        request.app.state.ask_slots.release()
    answer = "".join(event.get("text", "") for event in events if event.get("kind") == "token")
    return {
        "answer": answer,
        "events": events,
        "done": next((e for e in reversed(events) if e.get("kind") == "done"), None),
    }


@router.post("/feedback")
async def feedback(request: Request, body: FeedbackRequest):
    await _rate_limit(request, "write")
    identity = client_identity(request, request.app.state.settings.trusted_proxy_count)
    schema = request.app.state.settings.db_schema
    async with request.app.state.db.transaction() as conn:
        cur = await conn.execute(
            f"SELECT id FROM {schema}.query_logs WHERE id=%s", (body.query_log_id,)
        )
        if await cur.fetchone() is None:
            raise NotFoundError("Query log not found")
        cur = await conn.execute(
            f"INSERT INTO {schema}.feedback(query_log_id,rating,comment,client_key) "
            "VALUES (%s,%s,%s,%s) RETURNING id,query_log_id,rating,comment,created_at",
            (body.query_log_id, body.rating, body.comment, identity),
        )
        row = await cur.fetchone()
    return dict(zip(("id", "query_log_id", "rating", "comment", "created_at"), row, strict=True))


@router.get("/queries/{query_id}")
async def query_log(request: Request, query_id: int, _: str = Depends(require_admin)):
    schema = request.app.state.settings.db_schema
    async with request.app.state.db.connection() as conn:
        cur = await conn.execute(f"SELECT * FROM {schema}.query_logs WHERE id=%s", (query_id,))
        row = await cur.fetchone()
        if row is None:
            raise NotFoundError("Query log not found")
        return dict(zip([d.name for d in cur.description], row, strict=True))
