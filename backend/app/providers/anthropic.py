from __future__ import annotations

import inspect
import time
from collections.abc import AsyncIterator

from app.config.pipeline import LLMSpec, PipelineConfig
from app.config.settings import Settings
from app.core.errors import ConfigError
from app.generation.prompt import build_prompt
from app.models import ContextBlock, GenerationEvent
from app.providers.errors import classify_provider_error
from app.providers.gateway import ProviderGateway
from app.providers.profiles import ProviderProfile


class ClaudeGenerator:
    name = "claude"
    version = "claude:messages-stream-v2"

    def __init__(
        self,
        config: PipelineConfig | None = None,
        settings: Settings | None = None,
        client=None,
        llm_spec: LLMSpec | None = None,
        profile: ProviderProfile | None = None,
        gateway: ProviderGateway | None = None,
        **_: object,
    ):
        self.config = config or PipelineConfig()
        self.settings = settings
        self.spec = llm_spec or self.config.generator
        self.profile = profile
        self.gateway = gateway or ProviderGateway(settings, provider="anthropic")
        self.client = client
        self.last_failure = None
        if self.client is None and settings and settings.anthropic_api_key.get_secret_value():
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:
                raise ConfigError("Install the anthropic package to use Claude generation") from exc
            self.client = AsyncAnthropic(
                api_key=settings.anthropic_api_key.get_secret_value(),
                base_url=settings.anthropic_base_url,
                timeout=settings.anthropic_timeout_seconds,
            )

    async def stream(
        self, question: str, history: list[dict], blocks: list[ContextBlock]
    ) -> AsyncIterator[GenerationEvent]:
        if self.client is None:
            yield GenerationEvent(
                kind="error",
                code="provider_auth",
                message="Anthropic API key is not configured",
                retryable=False,
            )
            return
        prompt = build_prompt(
            getattr(self, "repo_name", "repository"),
            getattr(self, "commit_sha", "unknown"),
            question,
            blocks,
            max_question_chars=self.config.max_question_chars,
        )
        kwargs = {
            "model": self.spec.model,
            "max_tokens": self.spec.max_tokens,
            "system": prompt.system,
            "messages": [{"role": "user", "content": prompt.user}],
        }
        if self.spec.temperature is not None and self.spec.model not in {
            "claude-opus-4-7",
            "claude-opus-5",
        }:
            kwargs["temperature"] = self.spec.temperature
        started = time.perf_counter()
        first_token = None
        answer_tokens = 0
        input_tokens = output_tokens = None
        stop_reason = "end_turn"
        context = None
        stream = None
        try:

            async def open_stream():
                nonlocal context
                context = self.client.messages.stream(**kwargs)
                stream = await context.__aenter__()
                return stream

            stream = (
                await self.gateway.execute(
                    open_stream,
                    provider="anthropic",
                    operation_name="generate",
                    estimated_tokens=len(prompt.user),
                )
            ).value
            async for event in self._events(stream):
                if event.kind == "token":
                    if first_token is None:
                        first_token = time.perf_counter()
                    answer_tokens += len(event.text or "")
                yield event
            get_final = getattr(stream, "get_final_message", None)
            if get_final:
                final = get_final()
                if inspect.isawaitable(final):
                    final = await final
                usage = getattr(final, "usage", None)
                input_tokens = getattr(usage, "input_tokens", None)
                output_tokens = getattr(usage, "output_tokens", None)
                stop_reason = getattr(final, "stop_reason", stop_reason) or stop_reason
            yield GenerationEvent(
                kind="done",
                stats={
                    "provider": self.spec.provider,
                    "model": self.spec.model,
                    "tokens_in": input_tokens,
                    "tokens_out": output_tokens or answer_tokens,
                    "usage_source": "api" if input_tokens is not None else "estimated",
                    "first_token_ms": round(
                        ((first_token or time.perf_counter()) - started) * 1000
                    ),
                    "total_ms": round((time.perf_counter() - started) * 1000),
                    "stop_reason": stop_reason,
                    "truncated": stop_reason == "max_tokens",
                },
            )
        except Exception as exc:
            details = getattr(exc, "details", {}) or {}
            failure = classify_provider_error(exc, details.get("status_code"))
            self.last_failure = failure
            yield GenerationEvent(
                kind="error",
                code=failure.code,
                message=failure.message,
                retryable=failure.retryable,
            )
        finally:
            if context is not None:
                try:
                    await context.__aexit__(None, None, None)
                except Exception:
                    pass

    async def _events(self, stream):
        async for event in stream:
            if getattr(event, "type", "") == "content_block_delta":
                text = getattr(getattr(event, "delta", None), "text", None)
                if text:
                    yield GenerationEvent(kind="token", text=text)
