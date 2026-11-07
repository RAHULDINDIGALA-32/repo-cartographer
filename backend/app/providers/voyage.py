from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.config.pipeline import PipelineConfig
from app.config.settings import Settings
from app.core.errors import ConfigError, ProviderError
from app.ingestion.chunkers.tokens import count_tokens

from .gateway import ProviderGateway, ProviderHTTPError


class VoyageEmbedder:
    name = "voyage-code"

    def __init__(
        self,
        config: PipelineConfig | None = None,
        settings: Settings | None = None,
        gateway: ProviderGateway | None = None,
        transport: Callable[..., Awaitable[Any]] | None = None,
        **_: object,
    ):
        self.config = config or PipelineConfig()
        self.settings = settings
        if self.config.llm_chunk_summaries:
            raise ConfigError("llm_chunk_summaries is not implemented in B3")
        self.dimension = self.config.embedding_dim
        self.version = f"voyage:{self.config.embedding_model}:{self.dimension}"
        self.gateway = gateway or ProviderGateway(settings)
        self._transport = transport or self._http_transport
        self.last_accounting = {
            "requests": 0,
            "retries": 0,
            "tokens": 0,
            "throttle_wait_ms": 0,
            "latency_ms": 0,
        }

    async def _http_transport(self, texts: list[str], input_type: str) -> Any:
        if self.settings is None or not self.settings.voyage_api_key.get_secret_value():
            raise ConfigError("VOYAGE_API_KEY is required for embedding")
        timeout = self.settings.embed_timeout_seconds
        payload = {
            "input": texts,
            "model": self.config.embedding_model,
            "input_type": input_type,
            "output_dimension": self.dimension,
            "output_dtype": "float",
            "truncation": False,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.settings.voyage_api_key.get_secret_value()}"
                },
                json=payload,
            )
        if response.status_code >= 400:
            retry_after = response.headers.get("retry-after")
            raise ProviderHTTPError(
                response.status_code,
                "Voyage embedding request failed",
                float(retry_after) if retry_after else None,
            )
        return response.json()

    def _batches(self, texts: list[str]) -> list[tuple[int, list[str], int]]:
        max_texts = self.settings.embed_batch_max_texts if self.settings else 64
        max_tokens = self.settings.embed_batch_max_tokens if self.settings else 50_000
        max_tokens = max(1, int(max_tokens * 0.9))
        batches: list[tuple[int, list[str], int]] = []
        current: list[str] = []
        current_tokens = 0
        start = 0
        for index, text in enumerate(texts):
            tokens = count_tokens(text, self.config.tokenizer)
            if current and (len(current) >= max_texts or current_tokens + tokens > max_tokens):
                batches.append((start, current, current_tokens))
                start = index
                current = []
                current_tokens = 0
            current.append(text)
            current_tokens += tokens
        if current:
            batches.append((start, current, current_tokens))
        return batches

    @staticmethod
    def _vectors(response: Any) -> list[list[float]]:
        data = (
            response.get("data")
            if isinstance(response, dict)
            else getattr(response, "embeddings", response)
        )
        if not isinstance(data, list):
            raise ProviderError("Voyage response did not contain embeddings", retryable=False)
        if data and isinstance(data[0], dict):
            data = [
                item["embedding"] for item in sorted(data, key=lambda item: item.get("index", 0))
            ]
        return data

    def _validate(self, vectors: list[list[float]], expected: int) -> list[list[float]]:
        if len(vectors) != expected:
            raise ProviderError(
                f"Voyage returned {len(vectors)} vectors for {expected} texts", retryable=False
            )
        for vector in vectors:
            if len(vector) != self.dimension or not all(
                math.isfinite(float(value)) for value in vector
            ):
                raise ProviderError(
                    "Voyage returned an invalid vector dimension or value", retryable=False
                )
        return [[float(value) for value in vector] for vector in vectors]

    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        self.last_accounting = {
            "requests": 0,
            "retries": 0,
            "tokens": 0,
            "throttle_wait_ms": 0,
            "latency_ms": 0,
        }
        batches = self._batches(texts)

        async def one(batch: tuple[int, list[str], int]):
            _, values, tokens = batch
            result = await self.gateway.execute(
                lambda: self._transport(values, input_type),
                provider="voyage",
                operation_name="embed",
                estimated_tokens=tokens,
            )
            for key in self.last_accounting:
                self.last_accounting[key] += getattr(result.accounting, key)
            return batch[0], self._validate(self._vectors(result.value), len(values))

        results = await asyncio.gather(*(one(batch) for batch in batches))
        ordered: list[list[float] | None] = [None] * len(texts)
        for start, vectors in results:
            ordered[start : start + len(vectors)] = vectors
        return [vector for vector in ordered if vector is not None]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, "document")

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed([text], "query")
        return vectors[0]

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await self._embed(texts, "query")
