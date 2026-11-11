from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.config.pipeline import PipelineConfig
from app.core.errors import ConfigError
from app.providers.profiles import get_profile


@dataclass
class Pipeline:
    stages: dict[str, Any] = field(default_factory=dict)


REGISTRY: dict[str, dict[str, Callable[..., Any]]] = {
    k: {}
    for k in (
        "chunker",
        "enricher",
        "embedder",
        "analyzer",
        "retriever",
        "fusion",
        "reranker",
        "assembler",
        "generator",
    )
}


def register(kind: str, name: str, factory: Callable[..., Any]) -> None:
    if kind not in REGISTRY:
        raise ConfigError(f"Unknown stage kind: {kind}")
    REGISTRY[kind][name] = factory


def _make(kind: str, name: str, deps: dict[str, Any]):
    factory = REGISTRY[kind].get(name)
    if factory is None:
        alternatives = ", ".join(sorted(REGISTRY[kind])) or "none"
        raise ConfigError(
            f"Unknown {kind} implementation '{name}'. Registered: {alternatives}. "
            "Expected in a later milestone."
        )
    return factory(**deps)


def build_pipeline(config: PipelineConfig, deps: dict[str, Any] | None = None) -> Pipeline:
    from app.ingestion.chunkers import AstChunker, FixedChunker
    from app.providers.anthropic import ClaudeGenerator
    from app.providers.openai_compatible import OpenAICompatibleGenerator
    from app.providers.voyage import VoyageEmbedder
    from app.retrieval.analyzers import LLMAnalyzer, RuleAnalyzer
    from app.retrieval.assembly import DefaultContextAssembler
    from app.retrieval.bm25 import BM25Retriever
    from app.retrieval.dense import DenseRetriever
    from app.retrieval.hybrid import HybridRetriever, WeightedRRF
    from app.retrieval.rerank import VoyageReranker
    from app.retrieval.sparse import SparseRetriever, SymbolRetriever

    if "ast" not in REGISTRY["chunker"]:
        register("chunker", "ast", AstChunker)
    if "fixed" not in REGISTRY["chunker"]:
        register("chunker", "fixed", FixedChunker)
    if "voyage-code" not in REGISTRY["embedder"]:
        register("embedder", "voyage-code", VoyageEmbedder)
    if "dense" not in REGISTRY["retriever"]:
        register("retriever", "dense", DenseRetriever)
    register("retriever", "sparse", SparseRetriever)
    register("retriever", "symbol", SymbolRetriever)
    register("retriever", "bm25", BM25Retriever)
    register("retriever", "hybrid", HybridRetriever)
    if "default" not in REGISTRY["assembler"]:
        register("assembler", "default", DefaultContextAssembler)
    if "claude" not in REGISTRY["generator"]:
        register("generator", "claude", ClaudeGenerator)
    if "openai_compatible" not in REGISTRY["generator"]:
        register("generator", "openai_compatible", OpenAICompatibleGenerator)
    register("analyzer", "none", _PassthroughAnalyzer)
    register("analyzer", "rule", RuleAnalyzer)
    register("analyzer", "llm", LLMAnalyzer)
    register("reranker", "none", _NoopReranker)
    register("reranker", "voyage", VoyageReranker)
    if "rrf" not in REGISTRY["fusion"]:
        register("fusion", "rrf", WeightedRRF)
    deps = deps or {}
    names = {
        "chunker": config.chunker,
        "embedder": config.embedder,
        "retriever": config.retriever,
        "fusion": config.fusion,
        "reranker": config.reranker,
    }
    stages = {
        kind: _make(
            kind,
            name,
            {**deps, "config": config} if kind == "chunker" else {**deps, "config": config},
        )
        for kind, name in names.items()
    }
    if deps:
        analyzer = _make("analyzer", config.analysis, {**deps, "config": config})
        profile = get_profile(config.generator.provider)
        generator_factory = (
            ClaudeGenerator if profile.kind == "anthropic" else OpenAICompatibleGenerator
        )
        stages.update(
            analyzer=analyzer,
            assembler=_make("assembler", config.assembler.name, {**deps, "config": config}),
            generator=generator_factory(
                **deps, config=config, llm_spec=config.generator, profile=profile
            ),
        )
        stages["retriever"] = _make("retriever", config.retriever, {**deps, "config": config})
        stages["reranker"] = _make("reranker", config.reranker, {**deps, "config": config})
        if hasattr(stages["retriever"], "embedder"):
            stages["retriever"].embedder = stages["embedder"]
    return Pipeline(stages)


class _PassthroughAnalyzer:
    name = "none"
    version = "analyzer:1"

    def __init__(self, **_: object):
        pass

    async def analyze(self, query, history=None):
        from app.models import QueryAnalysis

        return QueryAnalysis(original_query=query, rewritten_query=query)


class _NoopReranker:
    name = "none"
    version = "reranker:1"

    def __init__(self, **_: object):
        pass

    async def rerank(self, query, hits, top_k):
        return [
            hit.model_copy(update={"source": "reranked", "rank": rank})
            for rank, hit in enumerate(hits[:top_k], 1)
        ]


class _NoopFusion:
    name = "rrf"
    version = "fusion:1"

    def __init__(self, **_: object):
        pass

    def fuse(self, ranked_lists, top_k):
        return ranked_lists[0][:top_k] if ranked_lists else []
