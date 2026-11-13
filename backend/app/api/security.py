from __future__ import annotations

import hashlib
import hmac
import re

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import ForbiddenError, UnauthorizedError

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
_admin_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)
_admin_bearer = HTTPBearer(auto_error=False)
_admin_api_key_dependency = Depends(_admin_api_key)
_admin_bearer_dependency = Depends(_admin_bearer)


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


def require_admin(
    request: Request,
    api_key: str | None = _admin_api_key_dependency,
    bearer: HTTPAuthorizationCredentials | None = _admin_bearer_dependency,
) -> str:
    settings = request.app.state.settings
    # Direct calls from is_admin()/metrics use the request-header fallback;
    # FastAPI injects the documented security dependencies for route calls.
    supplied = api_key if isinstance(api_key, str) else None
    if supplied is None and isinstance(bearer, HTTPAuthorizationCredentials):
        supplied = bearer.credentials
    supplied = supplied or request.headers.get("x-api-key")
    if not supplied:
        raise UnauthorizedError("Admin API key required")
    for index, secret in enumerate(settings.api_admin_keys):
        if hmac.compare_digest(supplied, secret.get_secret_value()):
            return f"admin:{index}"
    raise ForbiddenError("Invalid admin API key")


def is_admin(request: Request) -> bool:
    try:
        require_admin(request)
    except (UnauthorizedError, ForbiddenError):
        return False
    return True


def verify_hmac_signature(secret: str, body: bytes, signature: str) -> bool:
    """Verify a GitHub sha256 webhook signature over the raw request body."""
    if not secret or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
