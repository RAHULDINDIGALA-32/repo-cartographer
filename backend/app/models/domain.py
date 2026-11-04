from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.errors import InvalidRepoUrlError


class ValueModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class RepoRef(ValueModel):
    owner: str
    name: str
    url: str
    default_branch: str | None = None

    @model_validator(mode="after")
    def normalize(self):
        raw = self.url.strip().rstrip("/")
        if raw.endswith(".git"):
            raw = raw[:-4]
        prefix = "https://github.com/"
        if not raw.lower().startswith(prefix) or len(raw.split("/")) != 5:
            raise InvalidRepoUrlError("Only public GitHub repository URLs are supported")
        owner, name = raw[len(prefix) :].split("/")
        if owner != self.owner or name != self.name or not owner or not name:
            raise InvalidRepoUrlError("Repository URL and owner/name do not match")
        object.__setattr__(self, "url", f"{prefix}{owner}/{name}")
        return self


class SourceFile(ValueModel):
    repo_id: int
    path: str
    language: str | None = None
    content: str
    file_hash: str
    size_bytes: int

    @model_validator(mode="after")
    def valid_path(self):
        normalized = self.path.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/") or normalized != self.path:
            raise ValueError(
                "path must be relative, normalized with forward slashes, and contain no .."
            )
        return self


SymbolType = Literal[
    "function",
    "method",
    "class",
    "class_skeleton",
    "module_header",
    "doc_section",
    "config",
    "text_block",
]


class Chunk(ValueModel):
    repo_id: int
    path: str
    symbol: str | None = None
    symbol_type: SymbolType
    parent_symbol: str | None = None
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    text: str = Field(min_length=1)
    token_count: int = Field(ge=0)
    chunker_version: str
    embed_text: str | None = None
    search_text: str | None = None
    content_hash: str | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class ChunkRecord(Chunk):
    id: int
    file_id: int
    embedder_version: str | None = None


class EmbeddedChunk(Chunk):
    embedding: list[float]
    embedder_version: str

    def validate_dim(self, dimension: int):
        if len(self.embedding) != dimension:
            raise ValueError("embedding dimension mismatch")


class QueryAnalysis(ValueModel):
    original_query: str
    rewritten_query: str
    sub_queries: list[str] = []
    identifiers: list[str] = []
    path_hints: list[str] = []
    intent: Literal["locate", "explain", "trace_flow", "general"] = "general"


class RetrievalHit(ValueModel):
    chunk: ChunkRecord
    score: float
    source: Literal["dense", "sparse", "fused", "reranked"]
    rank: int = Field(ge=1)


class ContextBlock(ValueModel):
    index: int = Field(ge=1)
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    text: str
    symbol: str | None = None


class Citation(ValueModel):
    index: int
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    commit_sha: str
    url: str | None = None


class GenerationEvent(ValueModel):
    kind: Literal["token", "citations", "done", "error"]
    text: str | None = None
    citations: list[Citation] | None = None
    stats: dict | None = None
    code: str | None = None
    message: str | None = None


class IndexStats(ValueModel):
    files_added: int = 0
    files_modified: int = 0
    files_deleted: int = 0
    files_unchanged: int = 0
    chunks_created: int = 0
    chunks_embedded: int = 0
    chunks_reused: int = 0
    chunks_deleted: int = 0
    embed_tokens: int = 0


class HealthStatus(ValueModel):
    ok: bool
    migration_version: int | None = None
    extensions_ok: bool
    embedding_dim_match: bool
    details: dict = {}
