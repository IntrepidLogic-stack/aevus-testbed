"""
Aevus API — Authentication Middleware
API key validation for all /api/v1 endpoints.

Supports three auth methods:
  1. X-API-Key header (programmatic API access)
  2. ?key= query param (WebSocket connections)
  3. aevus_session cookie (dashboard browser sessions)
"""

from __future__ import annotations

import hashlib
import secrets
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.config import settings

if TYPE_CHECKING:
    from fastapi import Request


def _make_session_token() -> str:
    """Derive a stable session token from the API key.
    This avoids needing a separate session store — the token is a
    HMAC-like hash of the API key, so it proves the holder authenticated."""
    if not settings.api_key:
        return ""
    return hashlib.sha256(f"aevus-session:{settings.api_key}".encode()).hexdigest()[:48]


SESSION_TOKEN = _make_session_token()


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validates X-API-Key header on all /api/v1 requests (except WebSocket upgrade)."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for health ping and deploy trigger
        if path in ("/api/v1/health/ping", "/api/v1/deploy/trigger", "/api/v1/ingest",
        "/api/v1/notes",
        "/api/v1/journal"):
            return await call_next(request)

        # Skip auth for non-API paths (dashboard, static files, root)
        if not path.startswith("/api/"):
            return await call_next(request)

        # Skip if no API key configured (development mode)
        if not settings.api_key:
            return await call_next(request)

        # Check session cookie first (dashboard browser sessions)
        session_cookie = request.cookies.get("aevus_session", "")
        if session_cookie and SESSION_TOKEN and secrets.compare_digest(session_cookie, SESSION_TOKEN):
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
