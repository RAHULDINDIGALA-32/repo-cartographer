from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import typer

from app.config.pipeline import PipelineConfig
from app.config.settings import Settings
from app.core.logging import configure_logging
from app.db.migrate import MigrationRunner
from app.db.pool import Database

app = typer.Typer(help="Repo Cartographer backend CLI")
db_app = typer.Typer()
app.add_typer(db_app, name="db")
config_app = typer.Typer()
app.add_typer(config_app, name="config")
for name in ("repo", "index", "ask", "eval"):
    app.add_typer(typer.Typer(), name=name)


def load_settings():
    return Settings()


def load_pipeline():
    return PipelineConfig.from_yaml(Path(__file__).parents[2] / "config.yaml")


def make_runner(s, d):
    return MigrationRunner(
        d,
        Path(__file__).parents[1] / "migrations",
        schema=s.db_schema,
        embedding_dim=load_pipeline().embedding_dim,
    )


@db_app.command("migrate")
def migrate():
    async def run():
        s = load_settings()
        configure_logging(s.log_level, s.log_format or "console")
        d = Database(s)
        await d.open()
        try:
            typer.echo(f"Applied migrations: {await make_runner(s, d).run()}")
        finally:
            await d.close()

    asyncio.run(run())


@db_app.command("status")
def status():
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        try:
            typer.echo(await make_runner(s, d).status())
            typer.echo((await d.health()).model_dump())
        finally:
            await d.close()

    asyncio.run(run())


@db_app.command("reset")
def reset(confirm: bool = typer.Option(False, "--confirm")):
    s = load_settings()
    if s.env not in ("dev", "test"):
        raise typer.BadParameter("db reset is only allowed in dev or test")
    if not confirm:
        raise typer.BadParameter("pass --confirm to reset the database")

    async def run():
        d = Database(s)
        await d.open()
        try:
            async with d.connection() as c:
                await c.execute(f"DROP SCHEMA IF EXISTS {s.db_schema} CASCADE")
                await c.commit()
            await make_runner(s, d).run()
            typer.echo("Database reset complete")
        finally:
            await d.close()

    asyncio.run(run())


@config_app.command("show")
def config_show():
    s = load_settings()
    typer.echo({"settings": s.redacted(), "pipeline": load_pipeline().snapshot()})


@app.command()
def doctor():
    async def run():
        s = load_settings()
        checks = {
            "git": shutil.which("git") is not None,
            "data_dir": False,
            "db": False,
            "migrations": False,
            "embedding_dim": False,
            "anthropic_key": bool(s.anthropic_api_key.get_secret_value()),
            "voyage_key": bool(s.voyage_api_key.get_secret_value()),
        }
        try:
            s.data_dir.mkdir(parents=True, exist_ok=True)
            checks["data_dir"] = s.data_dir.is_dir()
        except OSError:
            pass
        d = Database(s)
        await d.open()
        try:
            h = await d.health()
            checks.update(
                db=h.ok,
                migrations=not (await make_runner(s, d).status())["pending"],
                embedding_dim=h.embedding_dim_match,
            )
        except Exception:
            pass
        finally:
            await d.close()
        for k, v in checks.items():
            typer.echo(f"{'PASS' if v else 'FAIL'} {k}")
        if not all(checks.values()):
            raise typer.Exit(1)

    asyncio.run(run())
