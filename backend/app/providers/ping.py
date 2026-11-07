from __future__ import annotations

import time

from app.config.pipeline import PipelineConfig
from app.config.settings import Settings
from app.providers.anthropic import ClaudeGenerator
from app.providers.openai_compatible import OpenAICompatibleGenerator
from app.providers.profiles import get_profile


async def ping_provider(
    name: str, settings: Settings, config: PipelineConfig, model: str | None = None
) -> dict:
    profile = get_profile(name)
    spec = config.generator.model_copy(
        update={"provider": name, "model": model or config.generator.model, "max_tokens": 8}
    )
    factory = ClaudeGenerator if profile.kind == "anthropic" else OpenAICompatibleGenerator
    generator = factory(config=config, settings=settings, llm_spec=spec, profile=profile)
    started = time.perf_counter()
    async for event in generator.stream("Reply with OK.", [], []):
        if event.kind == "error":
            return {
                "ok": False,
                "provider": name,
                "model": spec.model,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "code": event.code,
                "message": event.message,
                "retryable": event.retryable,
            }
        if event.kind == "done":
            return {
                "ok": True,
                "provider": name,
                "model": spec.model,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "stats": event.stats,
            }
    return {
        "ok": False,
        "provider": name,
        "model": spec.model,
        "code": "generation_empty",
        "message": "Provider returned no completion",
        "retryable": False,
    }
