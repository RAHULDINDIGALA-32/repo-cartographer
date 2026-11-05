from __future__ import annotations

import json
import shutil
from collections import Counter
from fnmatch import fnmatchcase
from pathlib import Path
from statistics import median
from time import perf_counter

import typer

from app.config.pipeline import PipelineConfig
from app.config.settings import Settings
from app.core.asyncio import run_async
from app.core.errors import AppError
from app.core.logging import bind_context, configure_logging
from app.db.migrate import MigrationRunner
from app.db.pool import Database
from app.ingestion.chunkers import AstChunker, FixedChunker
from app.ingestion.chunkers.ast import tree_dump
from app.repos_git.manager import RepoManager

app = typer.Typer(help="Repo Cartographer backend CLI")
db_app = typer.Typer()
app.add_typer(db_app, name="db")
config_app = typer.Typer()
app.add_typer(config_app, name="config")
repo_app = typer.Typer()
app.add_typer(repo_app, name="repo")
chunks_app = typer.Typer()
app.add_typer(chunks_app, name="chunks")
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


def _chunker(config: PipelineConfig, name: str):
    selected = config.model_copy(update={"chunker": name})
    return AstChunker(selected) if name == "ast" else FixedChunker(selected)


async def _chunk_inventory(
    repo_id: int, name: str, language: str | None = None, path_glob: str | None = None
):
    s = load_settings()
    d = Database(s)
    await d.open()
    try:
        manager = repo_manager(s, d)
        report = await manager.scan(repo_id)
        entries = [
            e
            for e in report.entries
            if (not language or e.language.lower() == language.lower())
            and (not path_glob or fnmatchcase(e.path, path_glob))
        ]
        chunker = _chunker(load_pipeline(), name)
        items = []
        started = perf_counter()
        for entry in entries:
            source = await manager.load_source_file(repo_id, entry)
            chunks = await __import__("asyncio").to_thread(chunker.chunk, source)
            items.append((source, chunks))
        elapsed = round((perf_counter() - started) * 1000, 2)
        return items, elapsed
    finally:
        await d.close()


def _stats(items, elapsed: float, config: PipelineConfig, name: str):
    chunks = [chunk for _, values in items for chunk in values]
    counts = Counter(chunk.symbol_type for chunk in chunks)
    by_language = {}
    for source, values in items:
        by_language.setdefault(source.language or "text", {"files": 0, "chunks": 0})
        by_language[source.language or "text"]["files"] += 1
        by_language[source.language or "text"]["chunks"] += len(values)
    tokens = sorted(chunk.token_count for chunk in chunks)
    p95 = tokens[min(len(tokens) - 1, int((len(tokens) - 1) * 0.95))] if tokens else 0
    fallback = Counter(chunk.fallback_reason for chunk in chunks if chunk.fallback_reason)
    per_file = sorted(
        ((source.path, len(values)) for source, values in items), key=lambda x: (-x[1], x[0])
    )[:10]
    return {
        "chunker": name,
        "files_processed": len(items),
        "chunks_total": len(chunks),
        "per_language": dict(sorted(by_language.items())),
        "by_symbol_type": dict(sorted(counts.items())),
        "token_distribution": {
            "min": tokens[0] if tokens else 0,
            "median": median(tokens) if tokens else 0,
            "p95": p95,
            "max": tokens[-1] if tokens else 0,
        },
        "below_min_chunk_tokens": sum(c.token_count < config.min_chunk_tokens for c in chunks),
        "above_budget": sum(c.token_count > config.max_chunk_tokens for c in chunks),
        "fallbacks": dict(sorted(fallback.items())),
        "symbol_share": round(sum(bool(c.symbol) for c in chunks) / len(chunks), 4)
        if chunks
        else 0,
        "top_files_by_chunk_count": [{"path": path, "chunks": count} for path, count in per_file],
        "processing_time_ms": elapsed,
    }


@chunks_app.command("stats")
def chunks_stats(
    repo_id: int,
    chunker: str = typer.Option("ast", "--chunker"),
    language: str | None = typer.Option(None, "--language"),
    path: str | None = typer.Option(None, "--path"),
    json_output: bool = typer.Option(False, "--json"),
):
    if chunker not in {"ast", "fixed"}:
        raise typer.BadParameter("chunker must be ast or fixed")

    async def run():
        try:
            items, elapsed = await _chunk_inventory(repo_id, chunker, language, path)
            result = _stats(items, elapsed, load_pipeline(), chunker)
            if json_output:
                typer.echo(json.dumps(result, sort_keys=True))
            else:
                typer.echo(
                    f"chunker: {chunker}\nfiles processed: {result['files_processed']}\nchunks total: {result['chunks_total']}"
                )
                typer.echo(f"languages: {result['per_language']}")
                typer.echo(f"symbol types: {result['by_symbol_type']}")
                typer.echo(f"tokens: {result['token_distribution']}")
                typer.echo(
                    f"below min: {result['below_min_chunk_tokens']}\nabove budget: {result['above_budget']}"
                )
                typer.echo(
                    f"fallbacks: {result['fallbacks']}\nsymbol share: {result['symbol_share']}"
                )
                typer.echo(
                    f"top files: {result['top_files_by_chunk_count']}\nprocessing time ms: {elapsed}"
                )
        except AppError as exc:
            cli_error(exc)

    run_async(run())


@chunks_app.command("show")
def chunks_show(repo_id: int, path: str, full: bool = typer.Option(False, "--full")):
    async def run():
        try:
            items, _ = await _chunk_inventory(repo_id, "ast", path_glob=path)
            for source, chunks in items:
                if source.path != path:
                    continue
                for index, chunk in enumerate(chunks, 1):
                    typer.echo(
                        f"[{index}] {chunk.start_line}-{chunk.end_line} {chunk.symbol_type} symbol={chunk.symbol!r} parent={chunk.parent_symbol!r} tokens={chunk.token_count}"
                    )
                    typer.echo(chunk.text if full else " ".join(chunk.text.strip().split())[:240])
                return
            raise typer.BadParameter(f"file not found in scan: {path}")
        except AppError as exc:
            cli_error(exc)

    run_async(run())


@chunks_app.command("compare")
def chunks_compare(repo_id: int):
    async def run():
        try:
            config = load_pipeline()
            ast_items, ast_time = await _chunk_inventory(repo_id, "ast")
            fixed_items, fixed_time = await _chunk_inventory(repo_id, "fixed")
            typer.echo(
                json.dumps(
                    {
                        "ast": _stats(ast_items, ast_time, config, "ast"),
                        "fixed": _stats(fixed_items, fixed_time, config, "fixed"),
                    },
                    sort_keys=True,
                )
            )
        except AppError as exc:
            cli_error(exc)

    run_async(run())


@chunks_app.command("tree")
def chunks_tree(repo_id: int, path: str, depth: int = typer.Option(4, "--depth")):
    async def run():
        try:
            items, _ = await _chunk_inventory(repo_id, "ast", path_glob=path)
            for source, _ in items:
                if source.path == path:
                    typer.echo(tree_dump(source, max(0, depth)))
                    return
            raise typer.BadParameter(f"file not found in scan: {path}")
        except AppError as exc:
            cli_error(exc)

    run_async(run())
