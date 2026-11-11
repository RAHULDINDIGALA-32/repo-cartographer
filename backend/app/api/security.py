from __future__ import annotations

import hashlib
import hmac
import re

from fastapi import Request

from app.core.errors import ForbiddenError, UnauthorizedError

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def client_identity(request: Request, trusted_proxy_count: int) -> str:
    key = request.headers.get("x-api-key")
    if key:
        return "key:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    host = request.client.host if request.client else "unknown"
    if trusted_proxy_count:
        forwarded = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",")]
        if len(forwarded) >= trusted_proxy_count:
            host = forwarded[-trusted_proxy_count]
    return "ip:" + hashlib.sha256(host.encode()).hexdigest()[:16]


def supplied_request_id(request: Request) -> str | None:
    value = request.headers.get("x-request-id")
    return value if value and _REQUEST_ID.fullmatch(value) else None


def require_admin(request: Request) -> str:
    settings = request.app.state.settings
    supplied = request.headers.get("x-api-key")
    if not supplied:
        raise UnauthorizedError("Admin API key required")
    for index, secret in enumerate(settings.api_admin_keys):
        if hmac.compare_digest(supplied, secret.get_secret_value()):
            return f"admin:{index}"
    raise ForbiddenError("Invalid admin API key")
