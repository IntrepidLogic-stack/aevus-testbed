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
import json
import secrets
import time
import urllib.request
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.config import settings

if TYPE_CHECKING:
    from fastapi import Request

# Cognito config
COGNITO_POOL_ID = "us-east-1_CVFBcLJV3"
COGNITO_REGION = "us-east-1"
COGNITO_ISSUER = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_POOL_ID}"
_jwks_cache = {"keys": None, "fetched_at": 0}


def _make_session_token() -> str:
    if not settings.api_key:
        return ""
    return hashlib.sha256(f"aevus-session:{settings.api_key}".encode()).hexdigest()[:48]


SESSION_TOKEN = _make_session_token()


def _get_cognito_jwks():
    """Fetch and cache Cognito JWKS (public keys)."""
    now = time.time()
    if _jwks_cache["keys"] and now - _jwks_cache["fetched_at"] < 3600:
        return _jwks_cache["keys"]
    try:
        url = f"{COGNITO_ISSUER}/.well-known/jwks.json"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            _jwks_cache["keys"] = data["keys"]
            _jwks_cache["fetched_at"] = now
            return _jwks_cache["keys"]
    except Exception:
        return _jwks_cache.get("keys")


def _validate_cognito_jwt(token: str) -> bool:
    """Validate a Cognito JWT token."""
    try:
        import jwt
        from jwt import PyJWKClient
        
        jwks_url = f"{COGNITO_ISSUER}/.well-known/jwks.json"
        jwk_client = PyJWKClient(jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=COGNITO_ISSUER,
            options={"verify_aud": False}  # Cognito ID tokens use 'aud', access tokens use 'client_id'
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
        if path in ("/api/v1/health/ping", "/api/v1/deploy/trigger", "/api/v1/ingest",
                     "/api/v1/notes", "/api/v1/journal", "/api/v1/auth/config"):
            return await call_next(request)

        # Skip if no API key configured (dev mode)
        if not settings.api_key:
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
