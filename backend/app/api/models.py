from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepoCreateRequest(StrictModel):
    url: str = Field(min_length=1, max_length=500)
    enqueue: bool = True
    public: bool = True


class SyncRequest(StrictModel):
    force: bool = False
    override_pin: bool = False


class AskOptions(StrictModel):
    k: int | None = Field(default=None, ge=1, le=100)
    path_prefix: str | None = Field(
        default=None, max_length=300, json_schema_extra={"example": None}
    )
    language: str | None = Field(default=None, max_length=50, json_schema_extra={"example": None})
    include_context: bool = False

    @field_validator("path_prefix", "language", mode="before")
    @classmethod
    def normalize_filter(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        # Swagger UI uses the literal word "string" for optional string
        # fields unless an example is supplied. Treat that placeholder as an
        # omitted filter instead of silently filtering every result out.
        return None if cleaned.lower() == "string" or not cleaned else cleaned


class AskRequest(StrictModel):
    question: str = Field(min_length=1, max_length=16_000)
    stream: bool = True
    options: AskOptions | None = None


class FeedbackRequest(StrictModel):
    query_log_id: int = Field(gt=0)
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=2_000)


class ErrorPayload(StrictModel):
    code: str
    message: str
    retryable: bool
    request_id: str
    details: dict[str, Any] | None = None


class ErrorResponse(StrictModel):
    error: ErrorPayload


class JobResponse(StrictModel):
    id: int
    repo_id: int
    type: str
    status: str
    attempts: int
    max_attempts: int
    run_after: Any
    error: str | None = None
    error_code: str | None = None
    trigger: str
    worker_id: str | None = None
    result: dict | None = None


class FeedbackResponse(StrictModel):
    id: int
    query_log_id: int
    rating: int
    comment: str | None = None
    created_at: Any
