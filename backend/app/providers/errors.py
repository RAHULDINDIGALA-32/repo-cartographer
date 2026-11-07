from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderFailure:
    code: str
    message: str
    retryable: bool
    status_code: int | None = None
    error_type: str | None = None
    retry_after: float | None = None


_SECRET = re.compile(r"(sk-[A-Za-z0-9_-]+|gsk_[A-Za-z0-9_-]+|Bearer\s+\S+)", re.I)


def safe_message(message: str) -> str:
    return _SECRET.sub("[redacted]", message)[:500]


def classify_provider_error(exc: BaseException, status_code: int | None = None) -> ProviderFailure:
    status = status_code or getattr(getattr(exc, "response", None), "status_code", None)
    text = safe_message(str(exc))
    lower = text.lower()
    retry_after = getattr(exc, "retry_after", None)
    if status in (401, 403):
        code, retryable = "provider_auth", False
    elif status == 402 or any(
        value in lower for value in ("insufficient credit", "quota exceeded", "billing")
    ):
        code, retryable = "provider_billing", False
    elif (
        status == 404
        or "model" in lower
        and any(value in lower for value in ("not found", "unknown", "does not exist"))
    ):
        code, retryable = "provider_model_not_found", False
    elif status == 400:
        code, retryable = "provider_bad_request", False
    elif status == 429:
        code, retryable = "provider_rate_limited", True
    elif status in (502, 503, 529) or status is not None and status >= 500:
        code, retryable = (
            "provider_overloaded" if status in (503, 529) else "provider_unavailable",
            True,
        )
    elif isinstance(exc, (TimeoutError, ConnectionError)) or "timeout" in lower:
        code, retryable = "provider_timeout", True
    else:
        code, retryable = "generation_internal", False
    return ProviderFailure(code, text or code, retryable, status, type(exc).__name__, retry_after)
