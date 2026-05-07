"""
Aevus API — Authentication Middleware
API key validation for all /api/v1 endpoints.

The dashboard is served as static HTML and doesn't go through this middleware.
WebSocket connections require the API key as a query parameter: ?key=<api_key>
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.config import settings

if TYPE_CHECKING:
    from fastapi import Request


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validates X-API-Key header on all /api/v1 requests (except WebSocket upgrade)."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for health ping (monitoring)
        if path in ("/api/v1/health/ping", "/api/v1/deploy/trigger"):
            return await call_next(request)

        # Skip auth for non-API paths (dashboard, static files, root, docs)
        if not path.startswith("/api/"):
            return await call_next(request)

        # Skip if no API key configured (development mode)
        if not settings.api_key:
            return await call_next(request)

        # WebSocket uses query param
        if path.endswith("/ws"):
            key = request.query_params.get("key", "")
        else:
            key = request.headers.get(settings.api_key_header, "")

        if not key or not secrets.compare_digest(key, settings.api_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)
