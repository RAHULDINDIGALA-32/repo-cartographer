"""Stable application errors used across boundaries."""

from typing import Any


class AppError(Exception):
    code = "app_error"
    http_status = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self):
        return self.message


class ConfigError(AppError):
    code = "config_error"
    http_status = 500


class DatabaseError(AppError):
    code = "database_error"
    http_status = 503


class MigrationError(AppError):
    code = "migration_error"
    http_status = 500


class InvalidRepoUrlError(AppError):
    code = "invalid_repo_url"
    http_status = 400


class RepoTooLargeError(AppError):
    code = "repo_too_large"
    http_status = 413


class RepoFetchError(AppError):
    code = "repo_fetch_error"
    http_status = 502


class IndexingError(AppError):
    code = "indexing_error"
    http_status = 500


class RetrievalError(AppError):
    code = "retrieval_error"
    http_status = 500


class GenerationError(AppError):
    code = "generation_error"
    http_status = 502


class GenerationProviderError(GenerationError):
    def __init__(self, code: str, message: str, *, retryable: bool, details=None):
        super().__init__(message, details=details)
        self.code = code
        self.retryable = retryable


class NotFoundError(AppError):
    code = "not_found"
    http_status = 404


class ConflictError(AppError):
    code = "conflict"
    http_status = 409


class ProviderError(AppError):
    code = "provider_error"
    http_status = 502

    def __init__(
        self, message: str, *, retryable: bool, retry_after: float | None = None, details=None
    ):
        super().__init__(message, details=details)
        self.retryable = retryable
        self.retry_after = retry_after


ERROR_HTTP_STATUS = {
    c.code: c.http_status
    for c in (
        ConfigError,
        DatabaseError,
        MigrationError,
        InvalidRepoUrlError,
        RepoTooLargeError,
        RepoFetchError,
        IndexingError,
        ProviderError,
        RetrievalError,
        GenerationError,
        GenerationProviderError,
        NotFoundError,
        ConflictError,
    )
}

ERROR_HTTP_STATUS.update(
    {
        "provider_auth": 502,
        "provider_billing": 502,
        "provider_model_not_found": 502,
        "provider_bad_request": 502,
        "provider_rate_limited": 502,
        "provider_overloaded": 502,
        "provider_unavailable": 502,
        "provider_timeout": 504,
        "generation_internal": 502,
    }
)
