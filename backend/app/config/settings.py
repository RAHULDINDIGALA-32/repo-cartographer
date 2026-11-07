from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str
    test_database_url: str = (
        "postgresql://cartographer:cartographer@localhost:55432/cartographer_test"
    )
    db_schema: str = "cartographer"
    db_pool_min: int = Field(1, ge=1)
    db_pool_max: int = Field(5, ge=1)
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_timeout_seconds: int = Field(120, gt=0)
    anthropic_max_concurrency: int = Field(4, ge=1)
    anthropic_rpm_limit: int | None = Field(None, ge=1)
    anthropic_tpm_limit: int | None = Field(None, ge=1)
    groq_api_key: SecretStr = SecretStr("")
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_seconds: int = Field(120, gt=0)
    groq_max_concurrency: int = Field(4, ge=1)
    groq_rpm_limit: int | None = Field(None, ge=1)
    groq_tpm_limit: int | None = Field(None, ge=1)
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: int = Field(120, gt=0)
    openrouter_max_concurrency: int = Field(4, ge=1)
    openrouter_rpm_limit: int | None = Field(None, ge=1)
    openrouter_tpm_limit: int | None = Field(None, ge=1)
    openrouter_site_url: str | None = None
    openrouter_app_name: str | None = None
    custom_api_key: SecretStr = SecretStr("")
    custom_base_url: str = "http://localhost:8000/v1"
    custom_timeout_seconds: int = Field(120, gt=0)
    custom_max_concurrency: int = Field(4, ge=1)
    voyage_api_key: SecretStr = SecretStr("")
    github_token: SecretStr = SecretStr("")
    data_dir: Path = Path("../data")
    log_level: str = "INFO"
    log_format: Literal["console", "json"] | None = None
    cors_origins: list[str] = ["http://localhost:5173"]
    max_repos: int = Field(5, ge=1)
    max_repo_files: int = Field(5000, ge=1)
    max_file_bytes: int = Field(500_000, ge=1)
    max_repo_source_bytes: int = Field(25_000_000, ge=1)
    max_chunks_per_repo: int = Field(15_000, ge=1)
    git_timeout_seconds: int = Field(120, gt=0)
    clone_timeout_seconds: int = Field(300, gt=0)
    git_max_concurrency: int = Field(2, ge=1)
    max_remote_repo_size_mb: int = Field(500, gt=0)
    provider_max_retries: int = Field(5, ge=0)
    provider_backoff_base_seconds: float = Field(1.0, gt=0)
    provider_backoff_max_seconds: float = Field(30.0, gt=0)
    embed_timeout_seconds: int = Field(60, gt=0)
    embed_max_concurrency: int = Field(2, ge=1)
    embed_batch_max_texts: int = Field(64, ge=1)
    embed_batch_max_tokens: int = Field(50_000, ge=1)
    voyage_rpm_limit: int | None = Field(None, ge=1)
    voyage_tpm_limit: int | None = Field(None, ge=1)
    index_window_files: int = Field(25, ge=1)
    index_stale_after_minutes: int = Field(30, gt=0)
    require_exact_tokenizer: bool = False
    query_embed_timeout_seconds: int = Field(20, gt=0)

    @model_validator(mode="after")
    def validate_pool(self):
        if self.db_pool_min > self.db_pool_max:
            raise ValueError("db_pool_min cannot exceed db_pool_max")
        if self.log_format is None:
            self.log_format = "json" if self.env == "prod" else "console"
        return self

    @field_validator("db_schema")
    @classmethod
    def valid_schema(cls, value):
        if not value or not value.replace("_", "").isalnum() or value[0].isdigit():
            raise ValueError("db_schema must be a simple SQL identifier")
        return value

    def redacted(self):
        result = self.model_dump(mode="json")
        for key in (
            "database_url",
            "test_database_url",
            "anthropic_api_key",
            "groq_api_key",
            "openrouter_api_key",
            "custom_api_key",
            "voyage_api_key",
            "github_token",
        ):
            if result.get(key):
                result[key] = "********"
        return result
