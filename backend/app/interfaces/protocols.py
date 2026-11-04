from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from app.models import (
    Chunk,
    ContextBlock,
    GenerationEvent,
    QueryAnalysis,
    RetrievalHit,
    SourceFile,
)


class Chunker(Protocol):
    name: str
    version: str

    def chunk(self, file: SourceFile) -> list[Chunk]: ...


class Enricher(Protocol):
    name: str
    version: str

    def enrich(self, chunk: Chunk, file: SourceFile) -> Chunk: ...


class Embedder(Protocol):
    name: str
    version: str
    dimension: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


class QueryAnalyzer(Protocol):
    name: str
    version: str

    async def analyze(self, query: str, history: list[dict] | None = None) -> QueryAnalysis: ...


class Retriever(Protocol):
    name: str
    version: str

    async def retrieve(
        self, repo_id: int, analysis: QueryAnalysis, top_k: int
    ) -> list[RetrievalHit]: ...


class Fuser(Protocol):
    name: str
    version: str

    def fuse(self, ranked_lists: list[list[RetrievalHit]], top_k: int) -> list[RetrievalHit]: ...


class Reranker(Protocol):
    name: str
    version: str

    async def rerank(
        self, query: str, hits: list[RetrievalHit], top_k: int
    ) -> list[RetrievalHit]: ...


class ContextAssembler(Protocol):
    name: str
    version: str

    def assemble(self, hits: list[RetrievalHit], token_budget: int) -> list[ContextBlock]: ...


class Generator(Protocol):
    name: str
    version: str

    def stream(
        self, question: str, history: list[dict], blocks: list[ContextBlock]
    ) -> AsyncIterator[GenerationEvent]: ...
