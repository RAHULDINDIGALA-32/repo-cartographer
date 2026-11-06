from __future__ import annotations

import inspect
import time
from collections.abc import AsyncIterator

from app.config.pipeline import PipelineConfig
from app.config.settings import Settings
from app.core.errors import ConfigError
from app.generation.prompt import build_prompt
from app.models import ContextBlock, GenerationEvent


class ClaudeGenerator:
    name = "claude"
    version = "claude:messages-stream-v1"

    def __init__(
        self,
        config: PipelineConfig | None = None,
        settings: Settings | None = None,
        client=None,
        **_: object,
    ):
        self.config = config or PipelineConfig()
        self.settings = settings
        self.client = client
        if self.client is None and settings and settings.anthropic_api_key.get_secret_value():
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:
                raise ConfigError("Install the anthropic package to use Claude generation") from exc
            self.client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())

    async def stream(
        self, question: str, history: list[dict], blocks: list[ContextBlock]
    ) -> AsyncIterator[GenerationEvent]:
        if self.client is None:
            yield GenerationEvent(
                kind="error", code="config_error", message="ANTHROPIC_API_KEY is required"
            )
            return
        prompt = build_prompt(
            getattr(self, "repo_name", "repository"),
            getattr(self, "commit_sha", "unknown"),
            question,
            blocks,
            max_question_chars=self.config.max_question_chars,
        )
        started = time.perf_counter()
        first_token = None
        answer_tokens = 0
        input_tokens = None
        output_tokens = None
        stop_reason = "end_turn"
        try:
            kwargs = {
                "model": self.config.generator_model,
                "max_tokens": self.config.max_answer_tokens,
                "system": prompt.system,
                "messages": [{"role": "user", "content": prompt.user}],
            }
            if (
                self.config.generator_temperature
                and "claude-4-7" not in self.config.generator_model
                and "claude-opus-5" not in self.config.generator_model
            ):
                kwargs["temperature"] = self.config.generator_temperature
            stream_context = self.client.messages.stream(**kwargs)
            if hasattr(stream_context, "__aenter__"):
                async with stream_context as stream:
                    async for event in self._events(stream):
                        if event.kind == "token" and first_token is None:
                            first_token = time.perf_counter()
                        if event.kind == "token":
                            answer_tokens += len(event.text or "")
                        yield event
                    get_final = getattr(stream, "get_final_message", None)
                    if get_final:
                        final_message = get_final()
                        if inspect.isawaitable(final_message):
                            final_message = await final_message
                        usage = getattr(final_message, "usage", None)
                        input_tokens = getattr(usage, "input_tokens", None)
                        output_tokens = getattr(usage, "output_tokens", None)
                        stop_reason = (
                            getattr(final_message, "stop_reason", stop_reason) or stop_reason
                        )
            else:
                with stream_context as stream:
                    for event in stream.text_stream:
                        if first_token is None:
                            first_token = time.perf_counter()
                        answer_tokens += len(event)
                        yield GenerationEvent(kind="token", text=event)
                    get_final = getattr(stream, "get_final_message", None)
                    if get_final:
                        final_message = get_final()
                        usage = getattr(final_message, "usage", None)
                        input_tokens = getattr(usage, "input_tokens", None)
                        output_tokens = getattr(usage, "output_tokens", None)
                        stop_reason = (
                            getattr(final_message, "stop_reason", stop_reason) or stop_reason
                        )
            yield GenerationEvent(
                kind="done",
                stats={
                    "tokens_in": input_tokens,
                    "tokens_out": output_tokens or answer_tokens,
                    "first_token_ms": round(
                        ((first_token or time.perf_counter()) - started) * 1000
                    ),
                    "total_ms": round((time.perf_counter() - started) * 1000),
                    "stop_reason": stop_reason,
                    "truncated": stop_reason == "max_tokens",
                },
            )
        except Exception:
            yield GenerationEvent(
                kind="error", code="generation_error", message="Claude generation failed safely"
            )

    async def _events(self, stream):
        async for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "content_block_delta":
                text = getattr(getattr(event, "delta", None), "text", None)
                if text:
                    yield GenerationEvent(kind="token", text=text)
