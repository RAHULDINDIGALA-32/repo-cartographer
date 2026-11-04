import pytest

from app.config.pipeline import PipelineConfig
from app.core.errors import ERROR_HTTP_STATUS, ConfigError
from app.interfaces.registry import build_pipeline, register


def test_error_codes_are_unique_and_mapped():
    assert len(ERROR_HTTP_STATUS) == 12


def test_registry_reports_unknown_and_builds_fake():
    with pytest.raises(ConfigError, match="Registered"):
        build_pipeline(PipelineConfig())
    for kind, name in (
        ("chunker", "ast"),
        ("embedder", "voyage-code"),
        ("retriever", "hybrid"),
        ("fusion", "rrf"),
        ("reranker", "voyage"),
    ):
        register(kind, name, lambda kind=kind, name=name, **deps: (kind, name))
    assert len(build_pipeline(PipelineConfig()).stages) == 5
