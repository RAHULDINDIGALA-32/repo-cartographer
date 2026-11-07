from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

from app.ingestion.tokenizer import split_identifiers
from app.models import QueryAnalysis

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "does",
    "do",
    "for",
    "from",
    "how",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "where",
    "which",
    "who",
    "why",
    "with",
    "in",
    "this",
    "that",
    "there",
    "when",
    "was",
}
_IDENTIFIER = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")
_QUOTED = re.compile(r"`([^`]+)`")
_WORD = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*")


def _identifier_candidates(query: str) -> list[str]:
    values: list[str] = []
    for value in _QUOTED.findall(query):
        if _IDENTIFIER.fullmatch(value):
            values.append(value)
    for value in _WORD.findall(query):
        if "_" in value or "." in value or re.search(r"[a-z][A-Z]", value):
            values.append(value)
    for match in re.finditer(r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(\s*\)", query):
        values.append(match.group(1))
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
            for part in value.split("."):
                if part not in seen:
                    seen.add(part)
                    result.append(part)
    return result[:8]


def _keywords(query: str, identifiers: list[str]) -> list[str]:
    identifier_parts = {part.lower() for value in identifiers for part in re.split(r"[_.-]", value)}
    tokens: list[str] = []
    for value in split_identifiers(query).split():
        if len(value) > 1 and value not in STOP_WORDS and value not in identifier_parts:
            if value not in tokens:
                tokens.append(value)
    return tokens[:8]


class RuleAnalyzer:
    name = "rule"
    version = "analyzer:rule-v1"

    def __init__(self, **_: object):
        pass

    async def analyze(self, query: str, history=None) -> QueryAnalysis:
        identifiers = _identifier_candidates(query)
        lower = query.lower()
        wants_tests = bool(re.search(r"\b(test|tests|testing|spec|example|examples)\b", lower))
        return QueryAnalysis(
            original_query=query,
            rewritten_query=query,
            identifiers=identifiers,
            keywords=_keywords(query, identifiers),
            wants_tests=wants_tests,
            source="rule",
        )


def _valid_path(value: str) -> bool:
    normalized = value.replace("\\", "/").strip().strip("/")
    return bool(normalized) and ".." not in normalized.split("/") and not normalized.startswith(".")


def parse_analysis_json(raw: str, original_query: str) -> QueryAnalysis | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    allowed_intents = {"locate", "explain", "trace_flow", "general"}
    identifiers = [str(item) for item in value.get("identifiers", []) if isinstance(item, str)]
    identifiers = [item for item in identifiers if _IDENTIFIER.fullmatch(item)][:8]
    keywords = [str(item).lower() for item in value.get("keywords", []) if isinstance(item, str)]
    keywords = [item for item in keywords if len(item) > 1][:8]
    sub_queries = [item for item in value.get("sub_queries", []) if isinstance(item, str)][:3]
    path_hints = [
        item.replace("\\", "/").strip("/")
        for item in value.get("path_hints", [])
        if isinstance(item, str)
    ]
    path_hints = [item for item in path_hints if _valid_path(item)][:3]
    rewritten = value.get("rewritten_query")
    if not isinstance(rewritten, str) or not rewritten.strip() or len(rewritten) > 2000:
        rewritten = original_query
    if not identifiers and not keywords and not sub_queries and not path_hints:
        return None
    return QueryAnalysis(
        original_query=original_query,
        rewritten_query=rewritten[:2000],
        sub_queries=[item[:500] for item in sub_queries],
        identifiers=identifiers,
        keywords=keywords,
        path_hints=path_hints,
        intent=value.get("intent") if value.get("intent") in allowed_intents else "general",
        wants_tests=bool(value.get("wants_tests", False)),
        source="llm",
    )


class LLMAnalyzer:
    name = "llm"
    version = "analyzer:llm-v1"

    def __init__(
        self,
        config=None,
        settings=None,
        call: Callable[[str], Awaitable[str]] | None = None,
        **_: object,
    ):
        self.config = config
        self.call = call
        self.rule = RuleAnalyzer()
        self.generator = None
        if (
            call is None
            and config is not None
            and settings is not None
            and config.analyzer is not None
        ):
            from app.providers.anthropic import ClaudeGenerator
            from app.providers.openai_compatible import OpenAICompatibleGenerator
            from app.providers.profiles import get_profile

            profile = get_profile(config.analyzer.provider)
            factory = ClaudeGenerator if profile.kind == "anthropic" else OpenAICompatibleGenerator
            self.generator = factory(
                config=config, settings=settings, llm_spec=config.analyzer, profile=profile
            )

    async def analyze(self, query: str, history=None) -> QueryAnalysis:
        if self.call is None and self.generator is None:
            fallback = await self.rule.analyze(query, history)
            return fallback.model_copy(update={"degraded": True})
        try:
            if self.call is not None:
                raw = await self.call(query)
            else:
                chunks = []
                async for event in self.generator.stream(
                    "Return JSON only. Use exactly these keys: intent, rewritten_query, "
                    "sub_queries, identifiers, keywords, path_hints, wants_tests. "
                    "Do not include markdown or explanations. Search query: " + query,
                    history or [],
                    [],
                ):
                    if event.kind == "token":
                        chunks.append(event.text or "")
                    elif event.kind == "error":
                        raise RuntimeError(event.message or "analyzer provider failed")
                raw = "".join(chunks)
            result = parse_analysis_json(raw, query)
            if result is None:
                raise ValueError("invalid analyzer JSON")
            return result
        except Exception:
            fallback = await self.rule.analyze(query, history)
            return fallback.model_copy(update={"degraded": True})
