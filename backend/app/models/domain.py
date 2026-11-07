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

    @classmethod
    def parse(cls, value: str) -> RepoRef:
        import re
        from urllib.parse import urlparse

        raw = value.strip()
        if not raw or any(ord(c) < 32 for c in raw) or any(c in raw for c in "\\\"';&|$`"):
            raise InvalidRepoUrlError("Repository URL is empty or contains invalid characters")
        owner = name = None
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", raw):
            owner, name = raw.split("/")
        elif raw.startswith("git@github.com:"):
            owner, name = raw[len("git@github.com:") :].split("/", 1)
        else:
            parsed = urlparse(raw if "://" in raw else f"https://{raw}")
            host = (parsed.hostname or "").lower()
            if host == "www.github.com":
                host = "github.com"
            if (
                host != "github.com"
                or parsed.password
                or (parsed.username and parsed.username != "git")
            ):
                raise InvalidRepoUrlError("Only public GitHub repositories are supported")
            if parsed.scheme not in ("https", "ssh"):
                raise InvalidRepoUrlError("Only HTTPS or GitHub SSH repository URLs are supported")
            if parsed.scheme == "ssh" and parsed.username not in (None, "git"):
                raise InvalidRepoUrlError("Only the git SSH user is supported")
            parts = parsed.path.strip("/").split("/")
            if len(parts) < 2:
                raise InvalidRepoUrlError("Repository owner and name are required")
            owner, name = parts[0], parts[1]
        name = name[:-4] if name.endswith(".git") else name
        allowed = re.compile(r"^[A-Za-z0-9_.-]+$")
        if (
            not owner
            or not name
            or not allowed.fullmatch(owner)
            or not allowed.fullmatch(name)
            or ".." in owner
            or ".." in name
        ):
            raise InvalidRepoUrlError("Repository owner and name are invalid")
        owner, name = owner.lower(), name.lower()
        return cls.model_construct(owner=owner, name=name, url=f"https://github.com/{owner}/{name}")

    @model_validator(mode="after")
    def normalize(self):
        parsed = self.parse(self.url)
        if parsed.owner != self.owner.lower() or parsed.name != self.name.lower():
            raise InvalidRepoUrlError("Repository URL and owner/name do not match")
        object.__setattr__(self, "owner", parsed.owner)
        object.__setattr__(self, "name", parsed.name)
        object.__setattr__(self, "url", parsed.url)
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


class Repo(ValueModel):
    id: int
    ref: RepoRef
    default_branch: str | None = None
    indexed_sha: str | None = None
    indexed_at: object | None = None
    status: Literal["registered", "indexing", "ready", "failed"]
    last_error: str | None = None
    last_checked_at: object | None = None
    last_queried_at: object | None = None
    created_at: object | None = None
    updated_at: object | None = None


class RepoRegistration(ValueModel):
    repo: Repo
    already_existed: bool = False


class RemoteInfo(ValueModel):
    default_branch: str
    head_sha: str


class RemoteCheck(ValueModel):
    remote_sha: str
    indexed_sha: str | None = None
    is_stale: bool
    default_branch: str


class FetchResult(ValueModel):
    head_sha: str
    cloned: bool
    previous_head_sha: str | None = None
    default_branch: str


class FileEntry(ValueModel):
    path: str
    file_hash: str
    size_bytes: int
    language: str


class FilterDecision(ValueModel):
    include: bool
    reason: str | None = None


class SkipSummary(ValueModel):
    reason: str
    count: int
    total_bytes: int


class ScanReport(ValueModel):
    repo_id: int
    head_sha: str
    entries: list[FileEntry]
    skipped: list[SkipSummary]
    total_included_files: int
    total_included_bytes: int
    scan_duration_ms: int
    skipped_paths: list[dict[str, str | int]] | None = None


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
    symbols: list[str] = Field(default_factory=list)
    part_index: int | None = Field(default=None, ge=1)
    part_count: int | None = Field(default=None, ge=1)
    fallback_reason: str | None = None
    enricher_version: str | None = None

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
    retryable: bool | None = None


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
