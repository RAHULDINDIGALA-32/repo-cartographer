from __future__ import annotations

from fnmatch import fnmatch

from app.models import QueryAnalysis, RetrievalHit

TEST_PATTERNS = (
    "tests/**",
    "test/**",
    "**/test_*.py",
    "**/*_test.py",
    "**/*.test.*",
    "**/*.spec.*",
)


def apply_priors(
    hits: list[RetrievalHit], analysis: QueryAnalysis, config
) -> tuple[list[RetrievalHit], list[dict]]:
    applied = []
    result = []
    for hit in hits:
        multiplier = 1.0
        reasons = []
        path = hit.chunk.path.replace("\\", "/")
        if not analysis.wants_tests and any(fnmatch(path, pattern) for pattern in TEST_PATTERNS):
            multiplier *= config.priors.test_multiplier
            if config.priors.test_multiplier != 1.0:
                reasons.append("test")
        if hit.chunk.symbol_type == "module_header" and config.priors.header_multiplier != 1.0:
            multiplier *= config.priors.header_multiplier
            reasons.append("header")
        if analysis.path_hints and any(
            path == hint or path.startswith(hint.rstrip("/") + "/") for hint in analysis.path_hints
        ):
            if config.priors.path_hint_multiplier != 1.0:
                multiplier *= config.priors.path_hint_multiplier
                reasons.append("path_hint")
        score = hit.score * multiplier
        result.append(hit.model_copy(update={"score": score}))
        if reasons:
            applied.append({"id": hit.chunk.id, "multiplier": multiplier, "reasons": reasons})
    result.sort(key=lambda item: (-item.score, item.rank, item.chunk.id))
    result = [hit.model_copy(update={"rank": rank}) for rank, hit in enumerate(result, 1)]
    return result, applied
