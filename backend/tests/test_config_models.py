from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config.pipeline import PipelineConfig
from app.core.errors import InvalidRepoUrlError
from app.models import Chunk, RepoRef


def test_pipeline_defaults_and_snapshot():
    config = PipelineConfig()
    assert config.snapshot()["embedding_dim"] == 1024
    with pytest.raises(ValidationError):
        PipelineConfig(top_k_final=31)
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate({"unknown": 1})


def test_repository_pipeline_config_uses_active_groq_model():
    config = PipelineConfig.from_yaml(Path(__file__).parents[2] / "config.yaml")
    assert config.generator.provider == "groq"
    assert config.generator.model == "openai/gpt-oss-120b"


def test_repo_url_and_chunk_invariants():
    assert (
        RepoRef(owner="octo", name="repo", url="https://github.com/octo/repo/").url
        == "https://github.com/octo/repo"
    )
    with pytest.raises(InvalidRepoUrlError):
        RepoRef(owner="octo", name="repo", url="https://gitlab.com/octo/repo")
    with pytest.raises(ValidationError):
        Chunk(
            repo_id=1,
            path="x",
            symbol_type="function",
            start_line=2,
            end_line=1,
            text="x",
            token_count=1,
            chunker_version="x",
        )
