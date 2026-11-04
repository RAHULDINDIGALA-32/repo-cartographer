from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator

from app.models import Chunk, GenerationEvent, SourceFile


class FakeEmbedder:
    name = "fake"
    version = "fake:1.0"

    def __init__(self, dimension=8):
        self.dimension = dimension

    def _vector(self, text):
        raw = hashlib.sha256(text.encode()).digest()
        return [(raw[i % len(raw)] / 255.0) for i in range(self.dimension)]

    async def embed_documents(self, texts):
        return [self._vector(t) for t in texts]

    async def embed_query(self, text):
        return self._vector(text)


class FakeChunker:
    name = "fake"
    version = "fake:1.0"

    def chunk(self, file: SourceFile):
        return [
            Chunk(
                repo_id=file.repo_id,
                path=file.path,
                symbol_type="text_block",
                start_line=i,
                end_line=i,
                text=line,
                token_count=len(line.split()),
                chunker_version=self.version,
            )
            for i, line in enumerate(file.content.splitlines(), 1)
            if line.strip()
        ]


class FakeReranker:
    name = "fake"
    version = "fake:1.0"

    async def rerank(self, query, hits, top_k):
        return hits[:top_k]


class FakeGenerator:
    name = "fake"
    version = "fake:1.0"

    async def stream(self, question, history, blocks) -> AsyncIterator[GenerationEvent]:
        yield GenerationEvent(kind="token", text="fake answer")
        yield GenerationEvent(kind="done", stats={"fake": True})
