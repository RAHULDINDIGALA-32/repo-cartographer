from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.config.pipeline import PipelineConfig
from app.core.errors import ConfigError


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
    from app.providers.voyage import VoyageEmbedder

    if not REGISTRY["chunker"]:
        register("chunker", "ast", AstChunker)
        register("chunker", "fixed", FixedChunker)
    if "voyage-code" not in REGISTRY["embedder"]:
        register("embedder", "voyage-code", VoyageEmbedder)
    deps = deps or {}
    names = {
        "chunker": config.chunker,
        "embedder": config.embedder,
        "retriever": config.retriever,
        "fusion": config.fusion,
        "reranker": config.reranker,
    }
    stages = {
        kind: _make(kind, name, {**deps, "config": config} if kind == "chunker" else deps)
        for kind, name in names.items()
    }
    return Pipeline(stages)
