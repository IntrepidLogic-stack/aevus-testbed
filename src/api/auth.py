"""
Aevus API — Authentication Middleware
Supports:
  1. X-API-Key header (programmatic API access)
  2. ?key= query param (WebSocket connections)
  3. aevus_session cookie (dashboard browser sessions)
  4. Authorization: Bearer <jwt> (AWS Cognito JWT)
"""

from __future__ import annotations

import hashlib
import secrets
from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.config import settings

if TYPE_CHECKING:
    from fastapi import Request

logger = structlog.get_logger()

# Cognito config
COGNITO_POOL_ID = "us-east-1_CVFBcLJV3"
COGNITO_REGION = "us-east-1"
COGNITO_ISSUER = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_POOL_ID}"

# Fail-open visibility: when api_key is empty the middleware lets ALL /api/
# traffic through unauthenticated (dev mode). That's fine locally but a
# silent hole in prod, so make a mis-provisioned box loud at startup.
if not settings.api_key:
    logger.warning(
        "auth_fail_open",
        detail="API_KEY is empty — all /api/ traffic is UNAUTHENTICATED. "
        "This is expected in dev; set API_KEY in production.",
    )


def _make_session_token() -> str:
    if not settings.api_key:
        return ""
    return hashlib.sha256(f"aevus-session:{settings.api_key}".encode()).hexdigest()[:48]


SESSION_TOKEN = _make_session_token()

# One PyJWKClient reused across requests. It caches the Cognito signing keys
# internally, so building it once avoids a JWKS network fetch on every Bearer
# request (the previous code constructed a fresh client per call). Lazily
# initialized so importing this module never does network I/O.
_jwk_client = None


def _validate_cognito_jwt(token: str) -> bool:
    """Validate a Cognito JWT against the pool's signing keys (cached client)."""
    global _jwk_client
    try:
        import jwt

        if _jwk_client is None:
            from jwt import PyJWKClient

            _jwk_client = PyJWKClient(f"{COGNITO_ISSUER}/.well-known/jwks.json")
        signing_key = _jwk_client.get_signing_key_from_jwt(token)

        jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=COGNITO_ISSUER,
            options={"verify_aud": False},  # Cognito ID tokens use 'aud', access tokens use 'client_id'
        )
        return True
    except Exception:
        return False


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for non-API paths
        if not path.startswith("/api/"):
            return await call_next(request)

        # Skip auth for health and deploy
        if path in (
            "/api/v1/health/ping",
            "/api/v1/deploy/trigger",
            "/api/v1/ingest",
            "/api/v1/notes",
            "/api/v1/journal",
            "/api/v1/auth/config",
        ):
            return await call_next(request)

        # Allow unauthenticated access request submissions (POST only) and auth config
        if path == "/api/v1/access-requests" and request.method == "POST":
            return await call_next(request)

        # Skip if no API key configured (dev mode)
        if not settings.api_key:
            return await call_next(request)

        # Demo mode: allow read-only API access for demo sessions
        referer = request.headers.get("referer", "")
        demo_header = request.headers.get("x-aevus-demo", "")
        if ("demo=true" in referer or demo_header == "true") and (
            request.method == "GET" or path.startswith("/api/v1/ai/")
        ):
            return await call_next(request)

        # 1. Check session cookie
        session_cookie = request.cookies.get("aevus_session", "")
        if session_cookie and SESSION_TOKEN and secrets.compare_digest(session_cookie, SESSION_TOKEN):
            return await call_next(request)

        # 2. Check Cognito Bearer token
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if _validate_cognito_jwt(token):
                return await call_next(request)

        # 3. Check API key (header or query param for WebSocket)
        if path.endswith("/ws"):
            key = request.query_params.get("key", "")
        else:
            key = request.headers.get(settings.api_key_header, "")

        if key and secrets.compare_digest(key, settings.api_key):
            return await call_next(request)

        return JSONResponse(status_code=401, content={"detail": "Invalid or missing credentials"})
