from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.errors import ConfigError


class LLMSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str
    model: str = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_provider(self):
        from app.providers.profiles import PROFILES

        if self.provider not in PROFILES:
            raise ValueError(
                f"Unknown LLM provider '{self.provider}'; configured providers: "
                f"{', '.join(PROFILES)}"
            )
        return self


class PriorsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    test_multiplier: float = Field(1.0, ge=0)
    header_multiplier: float = Field(1.0, ge=0)
    path_hint_multiplier: float = Field(1.0, ge=0)


class AssemblerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Literal["default"] = "default"
    max_chunks_per_file: int = Field(0, ge=0)
    near_duplicate_threshold: float = Field(1.0, ge=0, le=1)
    expand_parent: bool = False
    expand_adjacent_parts: bool = False
    expansion_max_blocks: int = Field(2, ge=0)


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
    analyzer: LLMSpec | None = None
    analysis: Literal["none", "rule", "llm"] = "none"
    retriever: Literal["dense", "sparse", "hybrid"] = "dense"
    hybrid_sources: list[Literal["dense", "sparse", "symbol"]] = ["dense", "sparse", "symbol"]
    fusion_weights: dict[str, float] = {
        "dense": 1.0,
        "dense_sub": 1.0,
        "sparse": 1.0,
        "symbol": 1.0,
    }
    fusion: str = "rrf"
    rrf_k: int = Field(60, gt=0)
    reranker: Literal["none", "voyage"] = "none"
    rerank_model: str = "rerank-2.5"
    rerank_doc_max_tokens: int = Field(600, gt=0)
    top_k_dense: int = Field(20, gt=0)
    top_k_sparse: int = Field(20, gt=0)
    top_k_symbol: int = Field(10, gt=0)
    top_k_fused: int = Field(30, gt=0)
    top_k_final: int = Field(8, gt=0)
    context_token_budget: int = Field(7000, gt=0)
    assembler: AssemblerConfig = AssemblerConfig()
    priors: PriorsConfig = PriorsConfig()
    analyzer_repo_map: bool = True
    generator: LLMSpec = LLMSpec(provider="groq", model="openai/gpt-oss-120b", max_tokens=1000)
    max_question_chars: int = Field(2000, gt=0)
    poll_interval_minutes: int = Field(15, gt=0)
    exclude_globs: list[str] = []
    include_globs: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def reject_old_llm_keys(cls, values):
        if isinstance(values, dict):
            if values.get("assembler") == "default":
                values = {**values, "assembler": {"name": "default"}}
            old = {
                key
                for key in values
                if key
                in {
                    "generator_model",
                    "generator_temperature",
                    "max_answer_tokens",
                    "analyzer_model",
                }
            }
            if old:
                raise ValueError(
                    f"Deprecated LLM keys {sorted(old)}; use generator="
                    "{provider,model,temperature,max_tokens} and analyzer instead"
                )
        return values

    @model_validator(mode="after")
    def validate_cross_fields(self):
        if self.min_chunk_tokens >= self.max_chunk_tokens:
            raise ValueError("min_chunk_tokens must be less than max_chunk_tokens")
        expected = {"voyage-code": 1024}.get(self.embedder)
        if expected is not None and self.embedding_dim != expected:
            raise ValueError(f"{self.embedder} requires embedding_dim={expected}")
        if self.top_k_final > self.top_k_fused:
            raise ValueError("top_k_final must be <= top_k_fused")
        if not self.hybrid_sources:
            raise ValueError("hybrid_sources must not be empty")
        if any(value < 0 for value in self.fusion_weights.values()):
            raise ValueError("fusion_weights must be non-negative")
        if self.analysis == "llm" and self.analyzer is None:
            raise ValueError("analysis='llm' requires an analyzer LLMSpec")
        return self

    @property
    def max_answer_tokens(self):
        return self.generator.max_tokens

    @property
    def generator_model(self):
        return self.generator.model

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
