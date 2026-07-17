"""API-key middleware.

Every /gx and /v1 call carries X-API-Key. Health and the OpenAPI surface are open so
that container healthchecks and Genesys data-action import both work unauthenticated.
"""

import hmac
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import get_settings

PUBLIC_PATHS = frozenset({"/health", "/docs", "/openapi.json"})

# /admin is a different trust domain: it has its own Basic auth (app/admin/auth.py).
# Skipping it here is what stops the gx key from being usable as an admin credential —
# the key never grants /admin, because /admin does not consult it at all.
UNCHECKED_PREFIXES = ("/admin",)

API_KEY_HEADER = "X-API-Key"


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(UNCHECKED_PREFIXES):
            return await call_next(request)

        supplied = request.headers.get(API_KEY_HEADER)
        expected = get_settings().api_key

        # compare_digest keeps the check constant-time; it needs str, not None.
        if supplied is None or not hmac.compare_digest(supplied, expected):
            return JSONResponse(
                status_code=401,
                content={"detail": f"Missing or invalid {API_KEY_HEADER}"},
            )

        return await call_next(request)
