from __future__ import annotations

import asyncio
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.limiter import TokenBucketLimiter
from app.api.routes import _error, router
from app.api.security import require_admin, supplied_request_id
from app.config.pipeline import PipelineConfig
from app.config.settings import Settings
from app.core.errors import AppError, DatabaseError
from app.core.logging import bind_context, configure_logging, unbind_context
from app.db.migrate import MigrationRunner
from app.db.pool import Database
from app.ingestion.indexer import Indexer
from app.jobs.scheduler import Scheduler
from app.jobs.worker import Worker
from app.observability import metrics
from app.repos_git.manager import RepoManager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _error_body(request: Request, code: str, message: str, status: int, *, details=None):
    body = {
        "error": {
            "code": code,
            "message": message,
            "retryable": status in {429, 503} or code.startswith("provider_"),
            "request_id": getattr(request.state, "request_id", "unknown"),
        }
    }
    if details:
        body["error"]["details"] = details
    response = JSONResponse(body, status_code=status)
    if status in {429, 503}:
        response.headers["Retry-After"] = "1"
    return response


def _pipeline_config_path() -> Path:
    """Resolve config in both the source tree and the container image."""
    candidates = (
        Path(__file__).parents[1] / "config.yaml",
        Path(__file__).parents[2] / "config.yaml",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


def create_app(settings: Settings | None = None, pipeline: PipelineConfig | None = None) -> FastAPI:
    runtime = settings or Settings()
    config = pipeline or PipelineConfig.from_yaml(_pipeline_config_path())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(runtime.log_level, runtime.log_format or "console")
        db = Database(runtime, embedding_dim=config.embedding_dim)
        await db.open()
        migration_runner = MigrationRunner(
            db,
            Path(__file__).parents[1] / "migrations",
            schema=runtime.db_schema,
            embedding_dim=config.embedding_dim,
        )
        pending = (await migration_runner.status())["pending"]
        if pending:
            await db.close()
            raise RuntimeError(f"Pending database migrations: {pending}")
        manager = RepoManager(db, runtime, config)
        app.state.db = db
        app.state.settings = runtime
        app.state.pipeline = config
        app.state.manager = manager
        app.state.indexer = Indexer(manager, runtime, config)
        app.state.worker = None
        app.state.scheduler = None
        app.state.worker_task = None
        app.state.scheduler_task = None
        if runtime.api_run_worker:
            worker = Worker(manager, runtime)
            scheduler = Scheduler(manager, runtime)
            app.state.worker = worker
            app.state.scheduler = scheduler
            app.state.worker_task = asyncio.create_task(worker.start())
            app.state.scheduler_task = asyncio.create_task(scheduler.start())
        try:
            yield
        finally:
            for service, task in (
                (app.state.scheduler, app.state.scheduler_task),
                (app.state.worker, app.state.worker_task),
            ):
                if service:
                    await service.stop(runtime.shutdown_grace_seconds)
                if task:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            await db.close()

    app = FastAPI(
        title="repo-cartographer",
        version="1.0",
        lifespan=lifespan,
        docs_url="/docs" if runtime.docs_enabled else None,
        redoc_url="/redoc" if runtime.docs_enabled else None,
        openapi_url="/openapi.json" if runtime.docs_enabled else None,
    )
    app.state.settings = runtime
    app.state.pipeline = config
    app.state.ask_limiter = TokenBucketLimiter(
        rate_per_minute=runtime.rate_limit_ask_per_minute,
        burst=runtime.rate_limit_ask_burst,
    )
    app.state.write_limiter = TokenBucketLimiter(
        rate_per_minute=runtime.rate_limit_write_per_minute,
        burst=runtime.rate_limit_write_per_minute,
    )
    app.state.ask_slots = asyncio.Semaphore(runtime.max_concurrent_asks)
    app.state.active_asks = 0
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime.cors_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "Authorization", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = supplied_request_id(request) or str(uuid4())
        bind_context(request_id=request.state.request_id)
        started = time.perf_counter()
        try:
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > runtime.max_request_body_bytes:
                return _error_body(request, "request_too_large", "Request body is too large", 413)
            response = await call_next(request)
            route = getattr(request.scope.get("route"), "path", None) or "unmatched"
            status_class = str(response.status_code // 100) + "xx"
            metrics.inc(
                "http_requests_total", method=request.method, route=route, status_class=status_class
            )
            metrics.observe(
                "http_request_duration_seconds",
                time.perf_counter() - started,
                method=request.method,
                route=route,
                status_class=status_class,
            )
            response.headers["X-Request-ID"] = request.state.request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Process-Time-Ms"] = str(
                round((time.perf_counter() - started) * 1000)
            )
            return response
        finally:
            unbind_context("request_id")

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return _error(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        details = {"fields": [".".join(str(p) for p in e["loc"]) for e in exc.errors()]}
        return _error_body(
            request, "validation_error", "Request validation failed", 422, details=details
        )

    @app.exception_handler(Exception)
    async def unknown_handler(request: Request, exc: Exception):
        return _error_body(request, "internal_error", "Internal server error", 500)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/metrics")
    async def metrics_endpoint(request: Request, _: str = Depends(require_admin)):
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.get("/ready")
    async def ready(request: Request):
        try:
            health_status = await request.app.state.db.health()
            if not health_status.ok:
                return JSONResponse(
                    {"ok": False, "details": health_status.model_dump(mode="json")}, 503
                )
            return {
                "ok": True,
                "details": health_status.model_dump(mode="json"),
                "worker_enabled": bool(request.app.state.worker),
            }
        except Exception as exc:
            raise DatabaseError("Readiness check failed") from exc

    app.include_router(router)
    return app


app = create_app()
