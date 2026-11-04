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
            "voyage_api_key",
            "github_token",
        ):
            if result.get(key):
                result[key] = "********"
        return result
