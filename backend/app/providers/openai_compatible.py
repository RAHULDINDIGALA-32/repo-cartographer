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


class _VisibleText:
    def __init__(self):
        self.thinking = False
        self.buffer = ""

    def feed(self, value: str) -> str:
        self.buffer += value
        visible = []
        while self.buffer:
            marker = "</think>" if self.thinking else "<think>"
            position = self.buffer.find(marker)
            if position < 0:
                if (
                    self.buffer.endswith("<")
                    or self.buffer.endswith("<think")
                    or self.buffer.endswith("</think")
                ):
                    keep = self.buffer.rfind("<")
                    visible.append(self.buffer[:keep])
                    self.buffer = self.buffer[keep:]
                elif not self.thinking:
                    visible.append(self.buffer)
                    self.buffer = ""
                break
            if not self.thinking:
                visible.append(self.buffer[:position])
            self.buffer = self.buffer[position + len(marker) :]
            self.thinking = not self.thinking
        return "".join(visible)

    def finish(self) -> str:
        if self.thinking:
            self.buffer = ""
            return ""
        value, self.buffer = self.buffer, ""
        return value


class OpenAICompatibleGenerator:
    name = "openai_compatible"
    version = "openai-compatible:chat-stream-v1"

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
        self.gateway = gateway or ProviderGateway(settings, provider=self.spec.provider)
        self.client = client
        if self.client is None and settings:
            key = getattr(
                settings, profile.key_setting if profile else f"{self.spec.provider}_api_key", None
            )
            if key and key.get_secret_value():
                try:
                    from openai import AsyncOpenAI
                except ImportError as exc:
                    raise ConfigError(
                        "Install the openai package to use OpenAI-compatible generation"
                    ) from exc
                base_url = getattr(
                    settings,
                    f"{self.spec.provider}_base_url",
                    profile.base_url if profile else None,
                )
                timeout = getattr(settings, f"{self.spec.provider}_timeout_seconds", 120)
                headers = {}
                if self.spec.provider == "openrouter":
                    if settings.openrouter_site_url:
                        headers["HTTP-Referer"] = settings.openrouter_site_url
                    if settings.openrouter_app_name:
                        headers["X-Title"] = settings.openrouter_app_name
                self.client = AsyncOpenAI(
                    api_key=key.get_secret_value(),
                    base_url=base_url,
                    timeout=timeout,
                    default_headers=headers or None,
                )

    async def stream(
        self, question: str, history: list[dict], blocks: list[ContextBlock]
    ) -> AsyncIterator[GenerationEvent]:
        if self.client is None:
            yield GenerationEvent(
                kind="error",
                code="provider_auth",
                message=f"{self.spec.provider} API key is not configured",
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
        messages = [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ]
        kwargs = {
            "model": self.spec.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": self.spec.max_tokens,
        }
        if self.spec.temperature is not None:
            kwargs["temperature"] = self.spec.temperature
        if self.spec.reasoning_effort is not None and self.spec.provider in {
            "groq",
            "openrouter",
            "custom",
        }:
            kwargs["reasoning_effort"] = self.spec.reasoning_effort
        started = time.perf_counter()
        first_token = None
        first_progress = None
        first_visible = None
        visible = _VisibleText()
        output_chars = 0
        usage = None
        stop_reason = "stop"
        stream = None
        try:
            stream = (
                await self.gateway.execute(
                    lambda: self.client.chat.completions.create(**kwargs),
                    provider=self.spec.provider,
                    operation_name="generate",
                    estimated_tokens=len(prompt.user),
                )
            ).value
            async for chunk in stream:
                if first_progress is None:
                    first_progress = time.perf_counter()
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                choice = choices[0]
                stop_reason = getattr(choice, "finish_reason", None) or stop_reason
                delta = getattr(choice, "delta", None)
                text = getattr(delta, "content", None) or ""
                if "<think>" in text:
                    yield GenerationEvent(kind="status", text="thinking")
                # Providers may put reasoning and visible content on the same
                # delta. Ignore only the reasoning fields; never discard the
                # visible content from that delta.
                text = visible.feed(text)
                if text:
                    if first_token is None:
                        first_token = time.perf_counter()
                    if first_visible is None:
                        first_visible = first_token
                    output_chars += len(text)
                    yield GenerationEvent(kind="token", text=text)
            trailing = visible.finish()
            if trailing:
                output_chars += len(trailing)
                yield GenerationEvent(kind="token", text=trailing)
            input_tokens = getattr(usage, "prompt_tokens", None)
            output_tokens = getattr(usage, "completion_tokens", None)
            yield GenerationEvent(
                kind="done",
                stats={
                    "provider": self.spec.provider,
                    "model": self.spec.model,
                    "tokens_in": input_tokens,
                    "tokens_out": output_tokens or max(1, output_chars // 4),
                    "usage_source": "api" if usage else "estimated",
                    "first_token_ms": round(
                        ((first_token or time.perf_counter()) - started) * 1000
                    ),
                    "first_progress_ms": round(
                        ((first_progress or time.perf_counter()) - started) * 1000
                    ),
                    "first_visible_token_ms": round(
                        ((first_visible or time.perf_counter()) - started) * 1000
                    ),
                    "total_ms": round((time.perf_counter() - started) * 1000),
                    "stop_reason": stop_reason,
                    "truncated": stop_reason == "length",
                },
            )
        except Exception as exc:
            details = getattr(exc, "details", {}) or {}
            failure = classify_provider_error(exc, details.get("status_code"))
            yield GenerationEvent(
                kind="error",
                code=failure.code,
                message=failure.message,
                retryable=failure.retryable,
            )
        finally:
            close = getattr(stream, "close", None)
            if close:
                result = close()
                if inspect.isawaitable(result):
                    await result
