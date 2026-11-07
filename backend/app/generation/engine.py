from __future__ import annotations

import time
from dataclasses import dataclass

from psycopg.types.json import Jsonb

from app.config.pipeline import PipelineConfig
from app.core.errors import ConflictError, NotFoundError
from app.generation.citations import CitationParser, validate_citations
from app.interfaces.registry import build_pipeline
from app.models import QueryAnalysis
from app.retrieval.priors import apply_priors


@dataclass(frozen=True)
class QueryOptions:
    top_k: int | None = None
    path_prefix: str | None = None
    language: str | None = None
    no_generate: bool = False
    history: list[dict] | None = None
    analysis: str | None = None
    retriever: str | None = None
    rerank: bool | None = None
    trace: bool = False


class QueryEngine:
    def __init__(self, db, settings, config: PipelineConfig | None = None, *, pipeline=None):
        self.db = db
        self.settings = settings
        self.config = config or PipelineConfig()
        self.pipeline = pipeline or build_pipeline(self.config, {"db": db, "settings": settings})
        self.schema = settings.db_schema

    async def _repo(self, repo_id: int):
        async with self.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT owner,name,status,indexed_sha,indexed_at FROM {self.schema}.repos WHERE id=%s",
                (repo_id,),
            )
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError("Repository not found")
        if row[2] != "ready":
            raise ConflictError("Repository is not ready for querying")
        return row

    async def _log(self, payload: dict) -> int | None:
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                f"INSERT INTO {self.schema}.query_logs(repo_id,query,rewritten_query,intent,indexed_sha,retrieved_chunk_ids,reranked_chunk_ids,answer,latencies_ms,tokens_in,tokens_out,citation_check,pipeline_config,error,trace) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (
                    payload["repo_id"],
                    payload["query"],
                    payload.get("rewritten_query"),
                    payload.get("intent"),
                    payload.get("indexed_sha"),
                    payload.get("retrieved_ids", []),
                    payload.get("final_ids", []),
                    payload.get("answer", ""),
                    Jsonb(payload.get("latencies_ms", {})),
                    payload.get("tokens_in"),
                    payload.get("tokens_out"),
                    Jsonb(payload.get("citation_check"))
                    if payload.get("citation_check") is not None
                    else None,
                    Jsonb(self.config.snapshot()),
                    payload.get("error"),
                    Jsonb(payload.get("trace", {})),
                ),
            )
            row = await cur.fetchone()
            return row[0] if row else None

    async def ask(self, repo_id: int, question: str, options: QueryOptions | None = None):
        options = options or QueryOptions()
        started = time.perf_counter()
        payload = {"repo_id": repo_id, "query": question, "latencies_ms": {}}
        answer = ""
        logged = False
        try:
            if not question.strip() or len(question) > self.config.max_question_chars:
                raise ValueError(f"question must be 1-{self.config.max_question_chars} characters")
            db_started = time.perf_counter()
            owner, name, _, indexed_sha, indexed_at = await self._repo(repo_id)
            payload["latencies_ms"]["db_acquire"] = round((time.perf_counter() - db_started) * 1000)
            t = time.perf_counter()
            analyzer = self.pipeline.stages.get("analyzer")
            analysis = (
                await analyzer.analyze(question, options.history)
                if analyzer
                else QueryAnalysis(original_query=question, rewritten_query=question)
            )
            payload.update(
                rewritten_query=analysis.rewritten_query,
                intent=analysis.intent,
                trace={"analysis": analysis.model_dump(mode="json"), "degraded": []},
            )
            if analysis.degraded:
                payload["trace"]["degraded"].append("analyzer")
            payload["latencies_ms"]["analysis"] = round((time.perf_counter() - t) * 1000)
            retriever = self.pipeline.stages["retriever"]
            retrieve_started = time.perf_counter()
            retrieve_k = (
                self.config.top_k_fused
                if retriever.name == "hybrid"
                else (
                    self.config.top_k_sparse
                    if retriever.name == "sparse"
                    else self.config.top_k_symbol
                    if retriever.name == "symbol"
                    else self.config.top_k_dense
                )
            )
            hits = await retriever.retrieve(
                repo_id,
                analysis,
                retrieve_k,
                path_prefix=options.path_prefix,
                language=options.language,
            )
            payload["latencies_ms"]["retrieve_wall"] = round(
                (time.perf_counter() - retrieve_started) * 1000
            )
            if hasattr(retriever, "last_trace"):
                payload["trace"].update(retriever.last_trace)
            payload["latencies_ms"].update(getattr(retriever, "last_latencies", {}))
            if getattr(retriever, "degraded", None):
                payload["trace"]["degraded"].extend(retriever.degraded)
            if retriever.name in {"hybrid", "dense", "sparse", "symbol"}:
                hits, applied_priors = apply_priors(hits, analysis, self.config)
                payload["trace"]["priors"] = applied_priors
            payload["indexed_sha"] = retriever.last_indexed_sha or indexed_sha
            payload["retrieved_ids"] = [hit.chunk.id for hit in hits]
            reranker = self.pipeline.stages.get("reranker")
            final_hits = (
                await reranker.rerank(
                    analysis.rewritten_query, hits, options.top_k or self.config.top_k_final
                )
                if reranker
                else hits[: self.config.top_k_final]
            )
            if getattr(reranker, "degraded", False):
                payload["trace"]["degraded"].append("reranker")
            payload["trace"]["reranked"] = [
                {"id": hit.chunk.id, "score": hit.score, "rank": hit.rank} for hit in final_hits
            ]
            payload["final_ids"] = [hit.chunk.id for hit in final_hits]
            assembler = self.pipeline.stages["assembler"]
            expanded = await assembler.expand(final_hits) if hasattr(assembler, "expand") else []
            blocks = assembler.assemble(final_hits + expanded, self.config.context_token_budget)
            payload["trace"]["assembly"] = getattr(assembler, "last_report", {})
            yield {
                "kind": "retrieval",
                "hits": [
                    {
                        "chunk_id": h.chunk.id,
                        "path": h.chunk.path,
                        "start_line": h.chunk.start_line,
                        "end_line": h.chunk.end_line,
                        "symbol": h.chunk.symbol,
                        "score": h.score,
                        "rank": h.rank,
                    }
                    for h in hits
                ],
                "indexed_sha": payload["indexed_sha"],
                "top_score": hits[0].score if hits else None,
                "count": len(hits),
                "kept": len(blocks),
                "dropped": getattr(assembler, "last_report", {}).get("dropped", 0),
                "context": [block.model_dump(mode="json") for block in blocks],
            }
            if options.no_generate:
                payload["latencies_ms"]["total"] = round((time.perf_counter() - started) * 1000)
                payload["query_log_id"] = await self._log(payload)
                logged = True
                yield {
                    "kind": "done",
                    "latencies_ms": payload["latencies_ms"],
                    "tokens_in": None,
                    "tokens_out": None,
                    "indexed_sha": payload["indexed_sha"],
                    "indexed_at": indexed_at,
                    "query_log_id": payload["query_log_id"],
                    "degraded": payload["trace"].get("degraded", []),
                    "trace": payload["trace"] if options.trace else None,
                }
                return
            generator = self.pipeline.stages["generator"]
            generator.repo_name = f"{owner}/{name}"
            generator.commit_sha = payload["indexed_sha"] or "unknown"
            parser = CitationParser()
            generator_stats = {}
            async for event in generator.stream(question, options.history or [], blocks):
                if event.kind == "token":
                    text = event.text or ""
                    answer += text
                    parser.feed(text)
                    yield {"kind": "token", "text": text}
                elif event.kind == "error":
                    payload["error"] = f"{event.code}: {event.message}"
                    payload["answer"] = answer
                    yield {
                        "kind": "error",
                        "code": event.code or "generation_internal",
                        "message": event.message or "Generation failed",
                        "retryable": event.retryable,
                    }
                    return
                elif event.kind == "done":
                    generator_stats = event.stats or {}
            result = validate_citations(
                answer, blocks, owner, name, payload["indexed_sha"] or "unknown"
            )
            payload["citation_check"] = result.as_dict()
            yield {
                "kind": "citations",
                "citations": [citation.model_dump(mode="json") for citation in result.citations],
                "validation": result.as_dict(),
            }
            payload["latencies_ms"].update(
                first_token=generator_stats.get("first_token_ms", 0),
                generate_total=generator_stats.get("total_ms", 0),
                total=round((time.perf_counter() - started) * 1000),
                provider=generator_stats.get("provider"),
                model=generator_stats.get("model"),
                usage_source=generator_stats.get("usage_source", "estimated"),
            )
            payload["answer"] = answer
            payload["query_log_id"] = await self._log(payload)
            logged = True
            yield {
                "kind": "done",
                "latencies_ms": payload["latencies_ms"],
                "tokens_in": generator_stats.get("tokens_in"),
                "tokens_out": generator_stats.get("tokens_out"),
                "provider": generator_stats.get("provider"),
                "model": generator_stats.get("model"),
                "usage_source": generator_stats.get("usage_source", "estimated"),
                "stop_reason": generator_stats.get("stop_reason"),
                "truncated": generator_stats.get("truncated", False),
                "indexed_sha": payload["indexed_sha"],
                "indexed_at": indexed_at,
                "query_log_id": payload["query_log_id"],
                "degraded": payload["trace"].get("degraded", []),
                "trace": payload["trace"] if options.trace else None,
            }
        except Exception as exc:
            payload["error"] = str(exc)
            yield {
                "kind": "error",
                "code": getattr(exc, "code", "query_error"),
                "message": str(exc),
            }
        finally:
            payload["latencies_ms"]["total"] = round((time.perf_counter() - started) * 1000)
            if not logged:
                try:
                    await self._log(payload)
                except Exception:
                    pass
