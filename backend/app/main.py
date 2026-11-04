from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config.pipeline import PipelineConfig
from app.config.settings import Settings
from app.core.logging import bind_context, configure_logging, unbind_context
from app.db.migrate import MigrationRunner
from app.db.pool import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = settings or Settings()
        configure_logging(runtime.log_level, runtime.log_format or "console")
        root = Path(__file__).parents[2]
        config = PipelineConfig.from_yaml(root / "config.yaml")
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
        app.state.db = db
        yield
        await db.close()

    runtime = settings
    app = FastAPI(title="repo-cartographer", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=(runtime.cors_origins if runtime else ["*"]),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid4()))
        bind_context(request_id=request_id)
        try:
            response = await call_next(request)
            response.headers["x-request-id"] = request_id
            return response
        finally:
            unbind_context("request_id")

    @app.get("/health")
    async def health(request: Request):
        return (await request.app.state.db.health()).model_dump(mode="json")

    return app


app = create_app()
