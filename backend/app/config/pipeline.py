from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.errors import ConfigError


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    chunker: str = "ast"
    max_chunk_tokens: int = Field(800, gt=0)
    min_chunk_tokens: int = Field(50, ge=0)
    chunk_overlap_lines: int = Field(3, ge=0)
    max_parse_error_ratio: float = Field(0.3, ge=0, le=1)
    max_chunks_per_file: int = Field(400, gt=0)
    tokenizer: str = "cl100k_base"
    parse_timeout_ms: int = Field(2000, gt=0)
    contextual_headers: bool = True
    llm_chunk_summaries: bool = False
    embedder: str = "voyage-code"
    embedding_model: str = "voyage-code-3"
    embedding_dim: int = Field(1024, gt=0)
    retriever: Literal["dense", "sparse", "hybrid"] = "hybrid"
    fusion: str = "rrf"
    rrf_k: int = Field(60, gt=0)
    reranker: Literal["none", "voyage"] = "voyage"
    rerank_model: str = "rerank-2.5"
    top_k_dense: int = Field(20, gt=0)
    top_k_sparse: int = Field(20, gt=0)
    top_k_fused: int = Field(30, gt=0)
    top_k_final: int = Field(8, gt=0)
    context_token_budget: int = Field(7000, gt=0)
    analyzer_model: str = "claude-3-5-haiku-latest"
    generator_model: str = "claude-sonnet-4-5"
    max_answer_tokens: int = Field(1000, gt=0)
    poll_interval_minutes: int = Field(15, gt=0)
    exclude_globs: list[str] = []
    include_globs: list[str] = []

    @model_validator(mode="after")
    def validate_cross_fields(self):
        if self.min_chunk_tokens >= self.max_chunk_tokens:
            raise ValueError("min_chunk_tokens must be less than max_chunk_tokens")
        expected = {"voyage-code": 1024}.get(self.embedder)
        if expected is not None and self.embedding_dim != expected:
            raise ValueError(f"{self.embedder} requires embedding_dim={expected}")
        if self.top_k_final > self.top_k_fused:
            raise ValueError("top_k_final must be <= top_k_fused")
        return self

    def snapshot(self):
        return self.model_dump(mode="json")

    @classmethod
    def from_yaml(cls, path: str | Path):
        try:
            values = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
            if not isinstance(values, dict):
                raise ConfigError("Pipeline config must be a mapping")
            return cls.model_validate(values)
        except ConfigError:
            raise
        except Exception as exc:
            raise ConfigError(f"Invalid pipeline config: {exc}") from exc
