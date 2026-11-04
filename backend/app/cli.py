from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import typer

from app.config.pipeline import PipelineConfig
from app.config.settings import Settings
from app.core.asyncio import run_async
from app.core.errors import AppError
from app.core.logging import bind_context, configure_logging
from app.db.migrate import MigrationRunner
from app.db.pool import Database
from app.repos_git.manager import RepoManager

app = typer.Typer(help="Repo Cartographer backend CLI")
db_app = typer.Typer()
app.add_typer(db_app, name="db")
config_app = typer.Typer()
app.add_typer(config_app, name="config")
repo_app = typer.Typer()
app.add_typer(repo_app, name="repo")
for name in ("index", "ask", "eval"):
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


def repo_manager(s, d):
    return RepoManager(d, s, load_pipeline())


def cli_error(exc: AppError):
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(1)


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

    run_async(run())


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

    run_async(run())


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

    run_async(run())


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

    run_async(run())


@repo_app.command("add")
def repo_add(url: str):
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        try:
            result = await repo_manager(s, d).register(url)
            repo = result.repo
            typer.echo(
                f"id: {repo.id}\nurl: {repo.ref.url}\nbranch: {repo.default_branch}\n"
                f"already_existed: {result.already_existed}"
            )
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())


@repo_app.command("list")
def repo_list():
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        try:
            for repo in await repo_manager(s, d).store.list_repos():
                present = repo_manager(s, d)._clone_dir(repo.id).is_dir()
                typer.echo(
                    f"{repo.id}\t{repo.ref.url}\t{repo.status}\t"
                    f"{(repo.indexed_sha or '')[:8]}\t{present}"
                )
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())


@repo_app.command("check")
def repo_check(repo_id: int):
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        bind_context(repo_id=repo_id)
        try:
            result = await repo_manager(s, d).check_remote(repo_id)
            typer.echo(
                f"remote_sha: {result.remote_sha}\nindexed_sha: {result.indexed_sha}\n"
                f"branch: {result.default_branch}\nstale: {result.is_stale}"
            )
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())


@repo_app.command("fetch")
def repo_fetch(repo_id: int):
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        bind_context(repo_id=repo_id)
        try:
            result = await repo_manager(s, d).fetch(repo_id)
            typer.echo(
                f"head_sha: {result.head_sha}\ncloned: {result.cloned}\n"
                f"branch: {result.default_branch}"
            )
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())


@repo_app.command("files")
def repo_files(
    repo_id: int,
    include: bool = typer.Option(False, "--include"),
    skipped: bool = typer.Option(False, "--skipped"),
    skip_reason: str | None = typer.Option(None, "--skip-reason"),
    json_output: bool = typer.Option(False, "--json"),
):
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        bind_context(repo_id=repo_id)
        try:
            report = await repo_manager(s, d).scan(
                repo_id, include_skipped=skipped, skipped_reason=skip_reason
            )
            payload = report.model_dump(mode="json")
            if json_output:
                typer.echo(json.dumps(payload))
                return
            typer.echo(
                f"included files: {report.total_included_files}\n"
                f"included bytes: {report.total_included_bytes}"
            )
            languages = Counter(entry.language for entry in report.entries)
            typer.echo(
                "languages: "
                + ", ".join(f"{key}={value}" for key, value in sorted(languages.items()))
            )
            typer.echo(
                "skipped: " + ", ".join(f"{item.reason}={item.count}" for item in report.skipped)
            )
            if include:
                for entry in report.entries:
                    typer.echo(entry.path)
            if skipped:
                for item in report.skipped_paths or []:
                    typer.echo(f"{item['path']}\t{item['reason']}\t{item['size_bytes']}")
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())


@repo_app.command("remove")
def repo_remove(repo_id: int, confirm: bool = typer.Option(False, "--confirm")):
    if not confirm:
        raise typer.BadParameter("pass --confirm to remove the repository")

    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        bind_context(repo_id=repo_id)
        try:
            await repo_manager(s, d).remove(repo_id)
            typer.echo("Repository removed")
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())
