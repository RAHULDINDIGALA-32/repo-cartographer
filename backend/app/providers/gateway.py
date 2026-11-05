from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from app.config.settings import Settings
from app.core.errors import ProviderError

log = structlog.get_logger(__name__)


class ProviderHTTPError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str = "provider request failed",
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class GatewayAccounting:
    provider: str
    operation: str
    requests: int = 1
    retries: int = 0
    tokens: int = 0
    throttle_wait_ms: int = 0
    latency_ms: int = 0


@dataclass(frozen=True)
class GatewayResult:
    value: Any
    accounting: GatewayAccounting


class ProviderGateway:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        max_retries: int | None = None,
        backoff_base: float | None = None,
        backoff_max: float | None = None,
        max_concurrency: int | None = None,
        rpm_limit: int | None = None,
        tpm_limit: int | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        random_fn: Callable[[], float] = random.random,
    ):
        self.max_retries = (
            max_retries
            if max_retries is not None
            else (settings.provider_max_retries if settings else 5)
        )
        self.backoff_base = (
            backoff_base
            if backoff_base is not None
            else (settings.provider_backoff_base_seconds if settings else 1.0)
        )
        self.backoff_max = (
            backoff_max
            if backoff_max is not None
            else (settings.provider_backoff_max_seconds if settings else 30.0)
        )
        self.max_concurrency = (
            max_concurrency
            if max_concurrency is not None
            else (settings.embed_max_concurrency if settings else 2)
        )
        self.rpm_limit = (
            rpm_limit
            if rpm_limit is not None
            else (settings.voyage_rpm_limit if settings else None)
        )
        self.tpm_limit = (
            tpm_limit
            if tpm_limit is not None
            else (settings.voyage_tpm_limit if settings else None)
        )
        self._sleep = sleep
        self._clock = clock
        self._random = random_fn
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._rate_lock = asyncio.Lock()
        self._request_times: deque[float] = deque()
        self._token_events: deque[tuple[float, int]] = deque()

    def _semaphore(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._semaphores:
            self._semaphores[provider] = asyncio.Semaphore(self.max_concurrency)
        return self._semaphores[provider]

    async def _throttle(self, estimated_tokens: int) -> int:
        waited = 0.0
        async with self._rate_lock:
            while True:
                now = self._clock()
                while self._request_times and now - self._request_times[0] >= 60:
                    self._request_times.popleft()
                while self._token_events and now - self._token_events[0][0] >= 60:
                    self._token_events.popleft()
                request_blocked = (
                    self.rpm_limit is not None and len(self._request_times) >= self.rpm_limit
                )
                token_total = sum(value for _, value in self._token_events)
                token_blocked = (
                    self.tpm_limit is not None
                    and token_total + estimated_tokens > self.tpm_limit
                    and token_total > 0
                )
                if not request_blocked and not token_blocked:
                    self._request_times.append(now)
                    self._token_events.append((now, estimated_tokens))
                    return round(waited * 1000)
                delays = []
                if request_blocked and self._request_times:
                    delays.append(60 - (now - self._request_times[0]))
                if token_blocked and self._token_events:
                    delays.append(60 - (now - self._token_events[0][0]))
                delay = max(0.001, min(delays))
                waited += delay
                await self._sleep(delay)

    @staticmethod
    def _failure(exc: Exception) -> tuple[int | None, float | None, bool]:
        if isinstance(exc, ProviderHTTPError):
            return (
                exc.status_code,
                exc.retry_after,
                exc.status_code == 429 or exc.status_code >= 500,
            )
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is not None:
            retry_after = getattr(getattr(exc, "response", None), "headers", {}).get("retry-after")
            try:
                retry_after = float(retry_after) if retry_after is not None else None
            except (TypeError, ValueError):
                retry_after = None
            return status, retry_after, status == 429 or status >= 500
        retryable = isinstance(
            exc,
            (
                TimeoutError,
                ConnectionError,
                asyncio.TimeoutError,
                httpx.TimeoutException,
                httpx.NetworkError,
            ),
        )
        return None, None, retryable

    async def execute(
        self,
        operation: Callable[[], Awaitable[Any]],
        *,
        provider: str,
        operation_name: str,
        estimated_tokens: int = 0,
    ) -> GatewayResult:
        retries = 0
        throttle_wait = await self._throttle(estimated_tokens)
        started = self._clock()
        async with self._semaphore(provider):
            for attempt in range(self.max_retries + 1):
                try:
                    value = await operation()
                    latency = round((self._clock() - started) * 1000)
                    accounting = GatewayAccounting(
                        provider,
                        operation_name,
                        retries=retries,
                        tokens=estimated_tokens,
                        throttle_wait_ms=throttle_wait,
                        latency_ms=latency,
                    )
                    log.info(
                        "provider_call",
                        provider=provider,
                        operation=operation_name,
                        attempt=attempt + 1,
                        latency_ms=latency,
                        status="success",
                    )
                    return GatewayResult(value, accounting)
                except Exception as exc:
                    status, retry_after, retryable = self._failure(exc)
                    if not retryable or attempt >= self.max_retries:
                        log.warning(
                            "provider_call_failed",
                            provider=provider,
                            operation=operation_name,
                            attempt=attempt + 1,
                            status=status or "transport",
                        )
                        raise ProviderError(
                            f"{provider} {operation_name} failed after {attempt + 1} attempt(s)",
                            retryable=retryable,
                            retry_after=retry_after,
                            details={"status_code": status} if status else None,
                        ) from exc
                    delay = (
                        retry_after
                        if retry_after is not None
                        else min(self.backoff_max, self.backoff_base * (2**attempt))
                        * self._random()
                    )
                    retries += 1
                    log.warning(
                        "provider_retry",
                        provider=provider,
                        operation=operation_name,
                        attempt=attempt + 1,
                        status=status or "transport",
                        delay_seconds=round(delay, 3),
                    )
                    await self._sleep(max(0, delay))
        raise ProviderError("Provider operation did not return", retryable=False)
