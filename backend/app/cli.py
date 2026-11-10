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
from app.evaluation import retrieval_metrics, validate_questions
from app.generation.engine import QueryEngine, QueryOptions
from app.ingestion.chunkers import AstChunker, FixedChunker
from app.ingestion.chunkers.ast import tree_dump
from app.ingestion.chunkers.tokens import tokenizer_identity
from app.ingestion.indexer import Indexer, IndexOptions
from app.interfaces.registry import build_pipeline
from app.providers.ping import ping_provider
from app.providers.profiles import PROFILES
from app.repos_git.manager import RepoManager
from app.retrieval.benchmark import benchmark_scratch, benchmark_vector

app = typer.Typer(help="Repo Cartographer backend CLI")
db_app = typer.Typer()
app.add_typer(db_app, name="db")
config_app = typer.Typer()
app.add_typer(config_app, name="config")
repo_app = typer.Typer()
app.add_typer(repo_app, name="repo")
chunks_app = typer.Typer()
app.add_typer(chunks_app, name="chunks")
index_app = typer.Typer()
app.add_typer(index_app, name="index")
bench_app = typer.Typer()
app.add_typer(bench_app, name="bench")
provider_app = typer.Typer()
app.add_typer(provider_app, name="provider")
eval_app = typer.Typer()
app.add_typer(eval_app, name="eval")


def load_settings():
    return Settings()


def load_pipeline():
    return PipelineConfig.from_yaml(Path(__file__).parents[2] / "config.yaml")


@provider_app.command("list")
def provider_list():
    settings = load_settings()
    config = load_pipeline()
    active = {config.generator.provider}
    for name, profile in PROFILES.items():
        key = getattr(settings, profile.key_setting)
        typer.echo(
            json.dumps(
                {
                    "provider": name,
                    "kind": profile.kind,
                    "base_url": getattr(settings, f"{name}_base_url", profile.base_url),
                    "key_configured": bool(key.get_secret_value()),
                    "active": name in active,
                },
                sort_keys=True,
            )
        )


@provider_app.command("ping")
def provider_ping(name: str, model: str | None = typer.Option(None, "--model")):
    async def run():
        settings = load_settings()
        try:
            result = await ping_provider(name, settings, load_pipeline(), model)
            typer.echo(json.dumps(result, sort_keys=True))
            if not result["ok"]:
                raise typer.Exit(1)
        except AppError as exc:
            cli_error(exc)

    run_async(run())


@eval_app.command("validate")
def eval_validate(path: Path = typer.Option(Path("../eval/questions.yaml"), "--path")):  # noqa: B008
    import yaml

    try:
        values = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        result = validate_questions(values)
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
        if not result["ok"]:
            raise typer.Exit(1)
    except OSError as exc:
        typer.echo(f"Error: cannot read evaluation file: {exc}", err=True)
        raise typer.Exit(1) from exc


@eval_app.command("retrieval")
def eval_retrieval(
    repo_id: int,
    path: Path = typer.Option(Path("../eval/questions.yaml"), "--path"),  # noqa: B008
    split: str = typer.Option("tune", "--split"),  # noqa: B008
    preset: str = typer.Option("dense", "--preset"),  # noqa: B008
    output: Path | None = typer.Option(None, "--output"),  # noqa: B008
):
    import yaml

    async def run():
        values = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        questions = [item for item in values if item.get("split") == split]
        s = load_settings()
        d = Database(s)
        await d.open()
        rows = []
        try:
            repo = await repo_manager(s, d).store.get_repo(repo_id)
            questions = [
                item
                for item in questions
                if item.get("repo") == repo.ref.url and item.get("verified", False)
            ]
            presets = yaml.safe_load(
                (Path(__file__).parents[2] / "eval" / "presets.yaml").read_text(encoding="utf-8")
            )
            base_config = load_pipeline()
            config_values = base_config.model_dump(mode="python")
            config_values.update(presets[preset])
            config = PipelineConfig.model_validate(config_values)
            engine = QueryEngine(d, s, config)
            for item in questions:
                try:
                    events = [
                        event
                        async for event in engine.ask(
                            repo_id, item["question"], QueryOptions(no_generate=True)
                        )
                    ]
                except Exception as exc:
                    rows.append({"id": item["id"], "error": str(exc)[:300]})
                    continue
                error = next((event for event in events if event["kind"] == "error"), None)
                if error:
                    rows.append({"id": item["id"], "error": error.get("message", "query failed")})
                    continue
                retrieval = next((event for event in events if event["kind"] == "retrieval"), None)
                hit_values = retrieval.get("hits", []) if retrieval else []
                context_values = retrieval.get("context", []) if retrieval else []
                rows.append(
                    {
                        "id": item["id"],
                        "metrics": retrieval_metrics(
                            hit_values, item.get("gold", []), context_values
                        ),
                        "retrieval": retrieval,
                    }
                )
        finally:
            await d.close()
        result = {
            "preset": preset,
            "split": split,
            "repo_id": repo_id,
            "repo_url": repo.ref.url,
            "selected": len(questions),
            "evaluated": sum("error" not in row for row in rows),
            "errored": sum("error" in row for row in rows),
            "skipped_unverified_or_other_repo": len(values) - len(questions),
            "rows": rows,
        }
        typer.echo(json.dumps(result, default=str, sort_keys=True))
        if output:
            output.write_text(json.dumps(result, default=str, indent=2), encoding="utf-8")
        if result["errored"]:
            raise typer.Exit(1)

    run_async(run())


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
def doctor(live: bool = typer.Option(False, "--live")):
    async def run():
        s = load_settings()
        checks = {
            "git": shutil.which("git") is not None,
            "data_dir": False,
            "db": False,
            "migrations": False,
            "embedding_dim": False,
            "voyage_key": bool(s.voyage_api_key.get_secret_value()),
            "tokenizer": False,
        }
        try:
            mode = tokenizer_identity(
                load_pipeline().tokenizer, require_exact=s.require_exact_tokenizer
            )
            checks["tokenizer"] = mode != "tok-estimate" or not s.require_exact_tokenizer
            typer.echo(f"INFO tokenizer_mode={mode}")
        except RuntimeError:
            pass
        try:
            s.data_dir.mkdir(parents=True, exist_ok=True)
            checks["data_dir"] = s.data_dir.is_dir()
        except OSError:
            pass
        d = Database(s)
        await d.open()
        try:
            active_provider = load_pipeline().generator.provider
            checks[f"{active_provider}_key"] = bool(
                getattr(s, f"{active_provider}_api_key").get_secret_value()
            )
            if live:
                result = await ping_provider(active_provider, s, load_pipeline())
                typer.echo(json.dumps({"provider_ping": result}, sort_keys=True))
                checks["provider_live"] = bool(result.get("ok"))
        except Exception:
            if live:
                checks["provider_live"] = False
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
                    f"{(repo.indexed_sha or '')[:8]}\t{present}\tpinned={repo.pinned}"
                )
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())


def _repo_pin_command(repo_id: int, pinned: bool):
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        try:
            await repo_manager(s, d).store.update_repo_fields(repo_id, pinned=pinned)
            typer.echo(f"Repository {repo_id} {'pinned' if pinned else 'unpinned'}")
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()
    run_async(run())


@repo_app.command("pin")
def repo_pin(repo_id: int):
    _repo_pin_command(repo_id, True)


@repo_app.command("unpin")
def repo_unpin(repo_id: int):
    _repo_pin_command(repo_id, False)


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


def make_indexer(s, d):
    return Indexer(repo_manager(s, d), s, load_pipeline())


def make_query_engine(s, d, config=None):
    return QueryEngine(d, s, config or load_pipeline())


@app.command("ask")
def ask_run(
    repo_id: int,
    question: str,
    k: int | None = typer.Option(None, "--k"),
    path: str | None = typer.Option(None, "--path"),
    language: str | None = typer.Option(None, "--language"),
    show_context: bool = typer.Option(False, "--show-context"),
    no_generate: bool = typer.Option(False, "--no-generate"),
    json_output: bool = typer.Option(False, "--json"),
    no_stream: bool = typer.Option(False, "--no-stream"),
    debug: bool = typer.Option(False, "--debug"),
    analysis: str | None = typer.Option(None, "--analysis"),
    retriever: str | None = typer.Option(None, "--retriever"),
    rerank: str | None = typer.Option(None, "--rerank"),
    preset: str | None = typer.Option(None, "--preset"),
    trace: bool = typer.Option(False, "--trace"),
):
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        try:
            config = load_pipeline()
            overrides = {}
            if analysis:
                overrides["analysis"] = analysis
            if retriever:
                overrides["retriever"] = retriever
            if rerank:
                overrides["reranker"] = "voyage" if rerank == "on" else "none"
            if preset:
                import yaml

                preset_path = Path(__file__).parents[2] / "eval" / "presets.yaml"
                presets = yaml.safe_load(preset_path.read_text(encoding="utf-8")) or {}
                if preset not in presets:
                    raise typer.BadParameter(f"unknown preset: {preset}")
                overrides.update(presets[preset])
            if overrides:
                values = config.model_dump(mode="python")
                values.update(overrides)
                config = PipelineConfig.model_validate(values)
            events = []
            async for event in make_query_engine(s, d, config).ask(
                repo_id,
                question,
                QueryOptions(
                    top_k=k,
                    path_prefix=path,
                    language=language,
                    no_generate=no_generate,
                    analysis=analysis,
                    retriever=retriever,
                    trace=trace,
                ),
            ):
                events.append(event)
                if json_output:
                    continue
                if event["kind"] == "retrieval" and show_context:
                    typer.echo(json.dumps(event, sort_keys=True))
                elif event["kind"] == "token" and not no_stream:
                    typer.echo(event.get("text", ""), nl=False)
                elif event["kind"] == "citations":
                    citations = event.get("citations", [])
                    validation = event.get("validation", {})
                    if citations:
                        typer.echo("\n\nSources:")
                        for citation in citations:
                            typer.echo(
                                f"[{citation['index']}] {citation['path']}:{citation['start_line']}-{citation['end_line']} {citation['url']}"
                            )
                    typer.echo(
                        "Citation summary: "
                        f"valid={len(validation.get('used', []))} "
                        f"invalid={len(validation.get('invalid', []))} "
                        f"unused={len(validation.get('unused_blocks', []))} "
                        f"uncited_answer={validation.get('uncited_answer', False)}"
                    )
                    if validation.get("uncited_answer") or validation.get("invalid"):
                        typer.echo("WARNING: citation validation found an issue.", err=True)
                elif event["kind"] == "done":
                    typer.echo(
                        "\n"
                        + json.dumps(
                            {
                                key: event.get(key)
                                for key in (
                                    "latencies_ms",
                                    "tokens_in",
                                    "tokens_out",
                                    "indexed_sha",
                                )
                            },
                            sort_keys=True,
                        )
                    )
                    if trace and event.get("trace") and not json_output:
                        typer.echo(json.dumps({"trace": event["trace"]}, sort_keys=True))
                elif event["kind"] == "error":
                    if debug:
                        typer.echo(json.dumps(event, sort_keys=True), err=True)
                    else:
                        typer.echo(f"Error [{event.get('code')}]: {event.get('message')}", err=True)
            if json_output:
                typer.echo(json.dumps(events, default=str, sort_keys=True))
            if events and events[-1].get("kind") == "error":
                raise typer.Exit(1)
        finally:
            await d.close()

    run_async(run())


@bench_app.command("vector")
def bench_vector(
    repo_id: int,
    json_output: bool = typer.Option(False, "--json"),
    scratch: bool = typer.Option(
        False,
        "--scratch",
        help="Run the capped local scratch-table trial; never use on Supabase free tier",
    ),
):
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        try:
            pipeline = build_pipeline(load_pipeline(), {"db": d, "settings": s})
            result = await (
                benchmark_scratch(pipeline.stages["retriever"], repo_id)
                if scratch
                else benchmark_vector(pipeline.stages["retriever"], repo_id)
            )
            typer.echo(
                json.dumps(result, sort_keys=True)
                if json_output
                else json.dumps(result, indent=2, sort_keys=True)
            )
        finally:
            await d.close()

    run_async(run())


@index_app.command("estimate")
def index_estimate(repo_id: int, chunker: str | None = typer.Option(None, "--chunker")):
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        try:
            typer.echo(
                json.dumps(
                    await make_indexer(s, d).estimate(repo_id, chunker=chunker),
                    default=str,
                    sort_keys=True,
                )
            )
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())


@index_app.command("run")
def index_run(
    repo_id: int,
    fetch: bool = typer.Option(False, "--fetch"),
    yes: bool = typer.Option(False, "--yes"),
    chunker: str | None = typer.Option(None, "--chunker"),
):
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        try:
            service = make_indexer(s, d)
            if not yes:
                estimate = await service.estimate(repo_id, chunker=chunker)
                typer.echo(json.dumps(estimate, default=str, sort_keys=True))
                if not typer.confirm("Proceed with indexing?"):
                    raise typer.Abort()
            result = await service.index_repo(repo_id, IndexOptions(fetch=fetch, chunker=chunker, no_fetch=not fetch))
            typer.echo(json.dumps(result, default=str, sort_keys=True))
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())


@index_app.command("plan")
def index_plan(repo_id: int, force: bool = typer.Option(False, "--force"), no_fetch: bool = typer.Option(False, "--no-fetch")):
    async def run():
        s = load_settings(); d = Database(s); await d.open()
        try:
            result = await make_indexer(s, d).plan(repo_id, IndexOptions(force=force, no_fetch=no_fetch))
            typer.echo(json.dumps(result, default=str, sort_keys=True))
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()
    run_async(run())


@index_app.command("sync")
def index_sync(repo_id: int, force: bool = typer.Option(False, "--force"), yes: bool = typer.Option(False, "--yes"), no_fetch: bool = typer.Option(False, "--no-fetch"), allow_pinned: bool = typer.Option(False, "--allow-pinned")):
    async def run():
        s = load_settings(); d = Database(s); await d.open()
        try:
            service = make_indexer(s, d)
            if not yes:
                plan = await service.plan(repo_id, IndexOptions(force=force, no_fetch=no_fetch))
                typer.echo(json.dumps(plan, default=str, sort_keys=True))
                if not typer.confirm("Proceed with sync?"):
                    raise typer.Abort()
            result = await service.sync_repo(repo_id, IndexOptions(force=force, no_fetch=no_fetch, allow_pinned=allow_pinned))
            typer.echo(json.dumps(result, default=str, sort_keys=True))
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()
    run_async(run())


@index_app.command("status")
def index_status(repo_id: int):
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        try:
            typer.echo(
                json.dumps(await make_indexer(s, d).status(repo_id), default=str, sort_keys=True)
            )
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())


@index_app.command("runs")
def index_runs(repo_id: int, json_output: bool = typer.Option(False, "--json")):
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        try:
            values = await make_indexer(s, d).runs(repo_id)
            typer.echo(
                json.dumps(values, default=str, sort_keys=True)
                if json_output
                else "\n".join(str(value) for value in values)
            )
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())


@index_app.command("verify")
def index_verify(repo_id: int, allow_drift: bool = typer.Option(False, "--allow-drift")):
    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        try:
            result = await make_indexer(s, d).verify(repo_id, allow_drift=allow_drift)
            typer.echo(json.dumps(result, default=str, sort_keys=True))
            if not result["ok"]:
                raise typer.Exit(1)
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())


@index_app.command("reset")
def index_reset(repo_id: int, confirm: bool = typer.Option(False, "--confirm")):
    if not confirm:
        raise typer.BadParameter("pass --confirm to reset the index")

    async def run():
        s = load_settings()
        d = Database(s)
        await d.open()
        try:
            await make_indexer(s, d).reset(repo_id)
            typer.echo("Index reset")
        except AppError as exc:
            cli_error(exc)
        finally:
            await d.close()

    run_async(run())


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


@chunks_app.command("verify")
def chunks_verify(repo_id: int, chunker: str = typer.Option("ast", "--chunker")):
    async def run():
        violations: list[dict[str, str | int]] = []
        try:
            items, _ = await _chunk_inventory(repo_id, chunker)
            config = load_pipeline()
            for source, chunks in items:
                lines = source.content.splitlines(keepends=True)
                covered = set()
                previous_end = 0
                for chunk in chunks:
                    expected = "".join(lines[chunk.start_line - 1 : chunk.end_line])
                    if chunk.text != expected:
                        violations.append(
                            {
                                "path": source.path,
                                "reason": "slice_mismatch",
                                "line": chunk.start_line,
                            }
                        )
                    if chunk.start_line < previous_end + 1 and chunk.start_line not in covered:
                        violations.append(
                            {"path": source.path, "reason": "overlap", "line": chunk.start_line}
                        )
                    if chunk.token_count > config.max_chunk_tokens:
                        violations.append(
                            {"path": source.path, "reason": "over_budget", "line": chunk.start_line}
                        )
                    covered.update(range(chunk.start_line, chunk.end_line + 1))
                    previous_end = max(previous_end, chunk.end_line)
                for line_no, line in enumerate(lines, 1):
                    if line.strip() and line_no not in covered:
                        violations.append(
                            {"path": source.path, "reason": "coverage_gap", "line": line_no}
                        )
            typer.echo(
                json.dumps(
                    {"ok": not violations, "files": len(items), "violations": violations},
                    sort_keys=True,
                )
            )
            if violations:
                raise typer.Exit(1)
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
