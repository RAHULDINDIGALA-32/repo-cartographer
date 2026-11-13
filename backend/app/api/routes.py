from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import quantiles

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.models import AskRequest, FeedbackRequest, RepoCreateRequest, SyncRequest
from app.api.security import (
    client_identity,
    is_admin,
    request_id,
    require_admin,
    verify_hmac_signature,
)
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
from app.models import RepoRef
from app.observability import metrics

router = APIRouter(prefix="/v1")


def _examples(url: str) -> list[str]:
    path = Path(__file__).parents[3] / "config" / "examples.yaml"
    if not path.exists():
        return []
    try:
        import yaml

        values = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(values.get(url, values.get("default", [])))[:8]
    except (OSError, TypeError, ValueError):
        return []


def _public_event(event: dict, body: AskRequest) -> dict:
    result = dict(event)
    if event.get("kind") == "retrieval":
        context = event.get("context", [])
        result["context"] = context if body.options and body.options.include_context else []
        if not result["context"]:
            result.pop("context", None)
        result["inspector_context_available"] = bool(context)
    elif event.get("kind") == "citations":
        # The retrieval event is transformed independently; citation snippets
        # are supplied when the caller requests context or when the generator
        # has already emitted the cited block in this event stream.
        result["citations"] = [
            {
                **citation,
                "snippet": citation.get("snippet", ""),
                "snippet_truncated": citation.get("snippet_truncated", False),
            }
            for citation in event.get("citations", [])
        ]
    return result


def _record_ask_event(event: dict, *, stream: bool):
    kind = event.get("kind")
    if kind == "done":
        metrics.inc("ask_requests_total", outcome="ok", stream=str(stream).lower())
        for stage, value in (event.get("latencies_ms") or {}).items():
            if isinstance(value, (int, float)):
                metrics.observe("ask_stage_duration_seconds", value / 1000, stage=stage)
        provider = event.get("provider") or "unknown"
        if event.get("tokens_in") is not None:
            metrics.inc(
                "ask_tokens_total",
                event["tokens_in"],
                direction="in",
                provider=provider,
            )
        if event.get("tokens_out") is not None:
            metrics.inc(
                "ask_tokens_total",
                event["tokens_out"],
                direction="out",
                provider=provider,
            )
        for component in event.get("degraded", []) or []:
            metrics.inc("degraded_total", component=component)
    elif kind == "citations":
        validation = event.get("validation") or {}
        if validation.get("uncited_answer"):
            result = "uncited"
        elif validation.get("invalid"):
            result = "invalid_marker"
        elif validation.get("variants_normalized"):
            result = "normalized_variant"
        else:
            result = "ok"
        metrics.inc("citation_check_total", result=result)
    elif kind == "error":
        metrics.inc(
            "ask_requests_total",
            outcome=event.get("code", "error"),
            stream=str(stream).lower(),
        )


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
    if not is_admin(request):
        repos = [repo for repo in repos if repo.public]
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
            "public": repo.public,
            "examples": _examples(repo.ref.url),
            "staleness": (
                None
                if repo.remote_sha is None or repo.indexed_sha is None
                else repo.remote_sha != repo.indexed_sha
            ),
        }
        for repo in repos
    ]


@router.get("/repos/{repo_id}")
async def get_repo(request: Request, repo_id: int):
    repo = await _repo(request, repo_id)
    if not repo.public and not is_admin(request):
        raise NotFoundError("Repository not found")
    runs = await request.app.state.indexer.runs(repo_id, 5)
    return {
        "repo": repo.model_dump(mode="json"),
        "runs": runs,
        "examples": _examples(repo.ref.url),
    }


@router.post("/repos")
async def add_repo(request: Request, body: RepoCreateRequest, _: str = Depends(require_admin)):
    registration = await request.app.state.manager.register(body.url)
    result = {
        "repo": registration.repo.model_dump(mode="json"),
        "already_existed": registration.already_existed,
    }
    if body.public != registration.repo.public:
        updated = await request.app.state.manager.store.update_repo_fields(
            registration.repo.id, public=body.public
        )
        result["repo"] = updated.model_dump(mode="json")
    if body.enqueue:
        result["enqueue"] = (
            await RepoService(request.app.state.db, request.app.state.settings).enqueue_sync(
                registration.repo.id, "api"
            )
        ).__dict__
    return result


@router.delete("/repos/{repo_id}")
async def delete_repo(
    request: Request,
    repo_id: int,
    override_pin: bool = False,
    _: str = Depends(require_admin),
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
        metrics.inc("ask_rejections_total", reason="concurrency")
        raise ServerBusyError("Ask concurrency limit reached")
    try:
        wait_ms = request.app.state.settings.ask_queue_wait_ms
        if wait_ms == 0:
            # wait_for(..., timeout=0) can cancel before Semaphore.acquire()
            # gets a chance to run, even when a slot is available.
            await slots.acquire()
        else:
            await asyncio.wait_for(slots.acquire(), wait_ms / 1000)
        request.state.ask_slot_acquired = True
        request.app.state.active_asks += 1
        metrics.set("active_asks", request.app.state.active_asks)
    except TimeoutError as exc:
        metrics.inc("ask_rejections_total", reason="concurrency_timeout")
        raise ServerBusyError("Ask concurrency limit reached") from exc


def _release_ask(request: Request):
    if not getattr(request.state, "ask_slot_acquired", False):
        return
    request.state.ask_slot_acquired = False
    request.app.state.ask_slots.release()
    request.app.state.active_asks = max(0, request.app.state.active_asks - 1)
    metrics.set("active_asks", request.app.state.active_asks)


@router.post("/repos/{repo_id}/ask")
async def ask(request: Request, repo_id: int, body: AskRequest):
    repo = await _repo(request, repo_id)
    if repo.status != "ready":
        raise RepoNotReadyError("Repository is not indexed and ready for questions")
    if not repo.public and not is_admin(request):
        raise NotFoundError("Repository not found")
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
                        _record_ask_event(event, stream=True)
                        event = _public_event(event, body)
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
                    number,
                    "error",
                    {"code": "provider_timeout", "message": "Ask timed out"},
                )
            finally:
                if current:
                    current.cancel()
                    await asyncio.gather(current, return_exceptions=True)
                await iterator.aclose()
                _release_ask(request)

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
            _record_ask_event(event, stream=False)
            events.append(_public_event(event, body))
    except TimeoutError as exc:
        raise AppError("Ask timed out") from exc
    finally:
        _release_ask(request)
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


def _since(value: str) -> datetime:
    hours = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}.get(value)
    if hours is None:
        raise ValueError("since must be 24h, 7d, or 30d")
    return datetime.now(UTC) - timedelta(hours=hours)


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {"p50": None, "p95": None, "count": 0}
    if len(values) == 1:
        return {"p50": values[0], "p95": values[0], "count": 1}
    points = quantiles(values, n=100, method="inclusive")
    return {"p50": points[49], "p95": points[94], "count": len(values)}


@router.get("/admin/stats")
async def admin_stats(
    request: Request,
    since: str = "24h",
    repo_id: int | None = None,
    _: str = Depends(require_admin),
):
    try:
        start = _since(since)
    except ValueError as exc:
        raise AppError(str(exc), details={"field": "since"}) from exc
    schema = request.app.state.settings.db_schema
    clause = "created_at >= %s"
    params: list = [start]
    if repo_id is not None:
        clause += " AND repo_id=%s"
        params.append(repo_id)
    async with request.app.state.db.connection() as conn:
        # Keep this projection aligned with migrations 0002/0004. Query logs
        # store the indexed SHA, but not an indexed_at column; repository
        # indexing timestamps belong to repos/index_runs.
        cur = await conn.execute(
            f"SELECT error,latencies_ms,tokens_in,tokens_out,citation_check,trace "
            f"FROM {schema}.query_logs WHERE {clause} ORDER BY id",
            params,
        )
        logs = await cur.fetchall()
        cur = await conn.execute(
            f"SELECT status,trigger,count(*) FROM {schema}.jobs GROUP BY status,trigger"
        )
        job_rows = await cur.fetchall()
        cur = await conn.execute(
            f"SELECT coalesce(sum(embed_tokens),0) FROM {schema}.index_runs WHERE started_at >= %s",
            (start,),
        )
        auto_sync_tokens = (await cur.fetchone())[0]
        cur = await conn.execute(
            f"SELECT rating,count(*) FROM {schema}.feedback WHERE created_at >= %s GROUP BY rating",
            (start,),
        )
        feedback_rows = await cur.fetchall()
    outcomes: dict[str, int] = {}
    stages: dict[str, list[float]] = {}
    tokens_in = tokens_out = 0
    citations = {"ok": 0, "uncited": 0, "invalid": 0, "normalized": 0}
    degraded: dict[str, int] = {}
    for row in logs:
        error = row[0]
        outcomes[error or "ok"] = outcomes.get(error or "ok", 0) + 1
        tokens_in += row[2] or 0
        tokens_out += row[3] or 0
        for stage, value in (row[1] or {}).items():
            if isinstance(value, (int, float)):
                stages.setdefault(stage, []).append(float(value))
        check = row[4] or {}
        if check.get("uncited_answer"):
            citations["uncited"] += 1
        elif check.get("invalid"):
            citations["invalid"] += 1
        else:
            citations["ok"] += 1
        if check.get("variants_normalized"):
            citations["normalized"] += 1
        for component in (row[5] or {}).get("degraded", []):
            degraded[component] = degraded.get(component, 0) + 1
    total = len(logs)
    citations["compliance_rate"] = citations["ok"] / total if total else None
    repos = await request.app.state.manager.store.list_repos()
    repo_summary = [
        {
            "id": repo.id,
            "indexed_sha": repo.indexed_sha,
            "indexed_at": repo.indexed_at,
            "stale": (
                None
                if repo.remote_sha is None or repo.indexed_sha is None
                else repo.remote_sha != repo.indexed_sha
            ),
            "drift_chunks": None,
            "last_reuse_ratio": None,
        }
        for repo in repos
        if repo_id is None or repo.id == repo_id
    ]
    return {
        "window": since,
        "asks": {"total": total, "by_outcome": outcomes},
        "latency_ms": {stage: _percentiles(values) for stage, values in stages.items()},
        "tokens": {"in": tokens_in, "out": tokens_out},
        "citations": citations,
        "degraded": degraded,
        "feedback": {
            "up": sum(count for rating, count in feedback_rows if rating == 1),
            "down": sum(count for rating, count in feedback_rows if rating == -1),
        },
        "budgets": {
            "ask": {
                "used": tokens_out,
                "limit": request.app.state.settings.ask_daily_token_budget,
            },
            "auto_sync": {
                "used": auto_sync_tokens,
                "limit": request.app.state.settings.auto_sync_daily_token_budget,
            },
        },
        "repos": repo_summary,
        "jobs": {
            "by_status": {
                status: sum(count for s, _, count in job_rows if s == status)
                for status, _, _ in job_rows
            },
            "by_trigger": {
                trigger: sum(count for _, t, count in job_rows if t == trigger)
                for _, trigger, _ in job_rows
            },
        },
    }


@router.get("/admin/queries")
async def admin_queries(
    request: Request,
    limit: int = 50,
    cursor: int | None = None,
    repo_id: int | None = None,
    outcome: str | None = None,
    since: str = "24h",
    _: str = Depends(require_admin),
):
    limit = min(max(limit, 1), 200)
    try:
        start = _since(since)
    except ValueError as exc:
        raise AppError(str(exc), details={"field": "since"}) from exc
    schema = request.app.state.settings.db_schema
    clauses = ["created_at >= %s"]
    params: list = [start]
    if cursor is not None:
        clauses.append("id < %s")
        params.append(cursor)
    if repo_id is not None:
        clauses.append("repo_id=%s")
        params.append(repo_id)
    if outcome:
        clauses.append("error=%s")
        params.append(outcome)
    async with request.app.state.db.connection() as conn:
        cur = await conn.execute(
            f"SELECT id,created_at,repo_id,left(query,200),error,latencies_ms,"
            f"tokens_in,tokens_out,citation_check FROM {schema}.query_logs "
            f"WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT %s",
            (*params, limit),
        )
        rows = await cur.fetchall()
    return {
        "items": [
            {
                "id": row[0],
                "created_at": row[1],
                "repo_id": row[2],
                "question": row[3],
                "outcome": row[4] or "ok",
                "latencies_ms": row[5],
                "tokens_in": row[6],
                "tokens_out": row[7],
                "citation_check": row[8],
            }
            for row in rows
        ],
        "next_cursor": rows[-1][0] if len(rows) == limit else None,
    }


@router.post("/webhooks/github")
async def github_webhook(request: Request):
    secret = request.app.state.settings.github_webhook_secret.get_secret_value()
    if not secret:
        raise NotFoundError("Webhook is disabled")
    body = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    if not verify_hmac_signature(secret, body, signature):
        from app.core.errors import UnauthorizedError

        raise UnauthorizedError("Invalid webhook signature")
    await _rate_limit(request, "write")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AppError("Invalid webhook JSON") from exc
    delivery_id = request.headers.get("x-github-delivery")
    if delivery_id:
        schema = request.app.state.settings.db_schema
        async with request.app.state.db.transaction() as conn:
            cur = await conn.execute(
                f"INSERT INTO {schema}.webhook_deliveries(delivery_id) VALUES (%s) "
                "ON CONFLICT DO NOTHING RETURNING delivery_id",
                (delivery_id,),
            )
            if await cur.fetchone() is None:
                return {"ok": True, "duplicate": True}
    event = request.headers.get("x-github-event", "")
    if event == "ping":
        return {"ok": True, "event": "ping"}
    if event != "push":
        return {"ok": True, "ignored": event or "unknown"}
    repository = payload.get("repository") or {}
    url = repository.get("html_url")
    ref = payload.get("ref")
    if not isinstance(url, str) or not isinstance(ref, str):
        return {"ok": True, "ignored": "missing_repository_or_ref"}
    try:
        canonical = RepoRef.parse(url).url
    except Exception:
        return {"ok": True, "ignored": "invalid_repository"}
    repo = await request.app.state.manager.store.get_repo_by_url(canonical)
    if repo is None or not repo.public or repo.pinned or ref != f"refs/heads/{repo.default_branch}":
        return {"ok": True, "ignored": "unregistered_pinned_or_non_default_branch"}
    queued = await RepoService(request.app.state.db, request.app.state.settings).enqueue_sync(
        repo.id, "webhook"
    )
    return {"ok": True, "repo_id": repo.id, "enqueue": queued.__dict__}
