from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.config.pipeline import PipelineConfig
from app.config.settings import Settings
from app.core.errors import ConfigError
from app.ingestion.chunkers.tokens import count_tokens
from app.models import RetrievalHit
from app.providers.gateway import ProviderGateway, ProviderHTTPError


class VoyageReranker:
    name = "voyage"
    version = "voyage-rerank:1"

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
        self.gateway = gateway or ProviderGateway(settings, provider="voyage")
        self.transport = transport or self._http_transport
        self.degraded = False
        self.last_accounting = {}

    async def _http_transport(self, query: str, documents: list[str]) -> Any:
        if self.settings is None or not self.settings.voyage_api_key.get_secret_value():
            raise ConfigError("VOYAGE_API_KEY is required for reranking")
        async with httpx.AsyncClient(timeout=self.settings.rerank_timeout_seconds) as client:
            response = await client.post(
                "https://api.voyageai.com/v1/rerank",
                headers={
                    "Authorization": f"Bearer {self.settings.voyage_api_key.get_secret_value()}"
                },
                json={
                    "query": query,
                    "documents": documents,
                    "model": self.config.rerank_model,
                    "top_k": len(documents),
                    "return_documents": False,
                    "truncation": True,
                },
            )
        if response.status_code >= 400:
            retry_after = response.headers.get("retry-after")
            raise ProviderHTTPError(
                response.status_code,
                "Voyage rerank request failed",
                float(retry_after) if retry_after else None,
            )
        return response.json()

    def _document(self, hit: RetrievalHit) -> str:
        chunk = hit.chunk
        header = f"path: {chunk.path}\nlines: {chunk.start_line}-{chunk.end_line}"
        if chunk.symbol:
            header += f"\nsymbol: {chunk.symbol} ({chunk.symbol_type})"
        text = f"{header}\n\n{chunk.text}"
        limit = self.config.rerank_doc_max_tokens
        if count_tokens(text, self.config.tokenizer) <= limit:
            return text
        # Preserve the header and apply a conservative character truncation;
        # Voyage also enforces the model context limit server-side.
        return text[: max(256, limit * 4)]

    async def rerank(self, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        candidates = hits[: self.config.top_k_fused]
        if not candidates:
            return []
        documents = [self._document(hit) for hit in candidates]
        self.degraded = False
        try:
            result = await self.gateway.execute(
                lambda: self.transport(query, documents),
                provider="voyage",
                operation_name="rerank",
                estimated_tokens=sum(count_tokens(doc, self.config.tokenizer) for doc in documents),
            )
            self.last_accounting = result.accounting.__dict__
            values = (
                result.value.get("data", [])
                if isinstance(result.value, dict)
                else getattr(result.value, "data", [])
            )
            ranked = []
            for item in values:
                index = (
                    int(item.get("index", -1))
                    if isinstance(item, dict)
                    else int(getattr(item, "index", -1))
                )
                score = (
                    item.get("relevance_score", 0.0)
                    if isinstance(item, dict)
                    else getattr(item, "relevance_score", 0.0)
                )
                if 0 <= index < len(candidates) and math.isfinite(float(score)):
                    ranked.append((float(score), candidates[index]))
            ranked.sort(key=lambda item: (-item[0], item[1].chunk.id))
            return [
                hit.model_copy(update={"score": score, "rank": rank, "source": "reranked"})
                for rank, (score, hit) in enumerate(ranked[:top_k], 1)
            ]
        except Exception:
            self.degraded = True
            return [
                hit.model_copy(update={"rank": rank, "source": "reranked"})
                for rank, hit in enumerate(candidates[:top_k], 1)
            ]
