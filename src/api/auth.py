"""
Aevus API — Authentication Middleware
Supports:
  1. X-API-Key header (programmatic API access)
  2. ?key= query param (WebSocket connections)
  3. aevus_session cookie (dashboard browser sessions)
  4. Authorization: Bearer <jwt> (AWS Cognito JWT)

Authentication (the middleware) is separate from authorization. The middleware
only answers "is this caller known?"; it admits any session cookie, any pool
user's bearer, and the shared master X-API-Key. Routes that mutate users or read
the access-request queue additionally depend on `require_admin`, which demands a
verified Cognito bearer whose `cognito:groups` contains "Admin". The shared
master key and non-admin users are rejected with 403 there.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

import structlog
from fastapi import HTTPException, Request  # noqa: TCH002 (FastAPI resolves `request: Request` at runtime)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.config import settings

logger = structlog.get_logger()

# Cognito config
COGNITO_POOL_ID = "us-east-1_CVFBcLJV3"
COGNITO_REGION = "us-east-1"
COGNITO_ISSUER = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_POOL_ID}"
# Cognito group that may use admin/user-management routes (pool groups are
# Admin / Operator / Viewer).
ADMIN_GROUP = "Admin"
# Door 1 least-privilege group: synthetic demo data ONLY. A token carrying it is
# denied every API route except DEMO_ALLOWED_PATHS (see APIKeyMiddleware). The
# console's synthetic dataset is client-side, so "no live data" is enforced here
# by refusing the live API outright. Deny wins over any other group on the token.
DEMO_GROUP = "DemoViewer"
# Unauthenticated POSTs: the sign-up form and the one-time-code request. Both are
# rate limited in-app; the code route answers identically for unknown addresses.
PUBLIC_POST_PATHS = frozenset({"/api/v1/access-requests", "/api/v1/demo-access/code"})
DEMO_ALLOWED_PATHS = frozenset({"/api/v1/health/ping", "/api/v1/demo-access/session"})

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


def _decode_cognito_jwt(token: str) -> dict[str, Any] | None:
    """Verify a Cognito JWT against the pool's signing keys (cached client).

    Returns the verified claims, or None if the token is missing, malformed,
    expired, wrongly signed, or from another issuer. Never raises.
    """
    global _jwk_client
    try:
        import jwt

        if _jwk_client is None:
            from jwt import PyJWKClient

            _jwk_client = PyJWKClient(f"{COGNITO_ISSUER}/.well-known/jwks.json")
        signing_key = _jwk_client.get_signing_key_from_jwt(token)

        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=COGNITO_ISSUER,
            options={"verify_aud": False},  # Cognito ID tokens use 'aud', access tokens use 'client_id'
        )
        return claims
    except Exception:
        return None


def _validate_cognito_jwt(token: str) -> bool:
    """Validate a Cognito JWT against the pool's signing keys (cached client)."""
    return _decode_cognito_jwt(token) is not None


def token_groups(claims: dict[str, Any] | None) -> list[str]:
    """Normalized ``cognito:groups`` list from verified claims (tolerates a bare string)."""
    groups = claims.get("cognito:groups", []) if claims else []
    return [groups] if isinstance(groups, str) else list(groups)


def is_demo_identity(claims: dict[str, Any] | None) -> bool:
    """True if the verified token carries the synthetic-only DemoViewer group."""
    return DEMO_GROUP in token_groups(claims)


def bearer_claims(request: Request) -> dict[str, Any] | None:
    """Verified Cognito claims from the Authorization header, or None."""
    auth_header = request.headers.get("authorization", "")
    return _decode_cognito_jwt(auth_header[7:]) if auth_header.startswith("Bearer ") else None


def require_admin(request: Request) -> dict[str, Any]:
    """FastAPI dependency: allow only a verified Cognito bearer in the Admin group.

    Verifies the bearer itself rather than trusting the middleware, because the
    middleware also admits the shared master X-API-Key, session cookies, demo
    referers and every non-admin pool user. All of those get 403 here. The
    shared master key is deliberately NOT an admin credential: it carries no
    identity, so user-management actions would be unattributable.

    Returns the verified claims so handlers can attribute the action.
    """
    auth_header = request.headers.get("authorization", "")
    claims: dict[str, Any] | None = None
    if auth_header.startswith("Bearer "):
        claims = _decode_cognito_jwt(auth_header[7:])

    groups = claims.get("cognito:groups", []) if claims else []
    if isinstance(groups, str):  # defensive: tolerate a single-string claim
        groups = [groups]
    if claims is None or ADMIN_GROUP not in groups:
        logger.warning(
            "admin_access_denied",
            path=request.url.path,
            method=request.method,
            reason="no_valid_bearer" if claims is None else "not_in_admin_group",
        )
        raise HTTPException(status_code=403, detail="Admin role required")
    return claims


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
        ):
            return await call_next(request)
        # NOTE: /ingest stays exempt — it's the shop-PC relay's HTTP push path
        # and has no key today; hardening it needs a shared ingest secret sent
        # by the relay (follow-up, ARCHITECTURE_REVIEW H3). /notes and /journal
        # were previously exempt too, which let ANYONE POST operator notes / the
        # "immutable" journal with no auth. Removed: their GET reads still flow
        # through the demo/auth branches below; their writes now require auth.

        # Allow unauthenticated access request submissions (POST only)
        if request.method == "POST" and path in PUBLIC_POST_PATHS:
            return await call_next(request)

        # Skip if no API key configured (dev mode)
        if not settings.api_key:
            return await call_next(request)

        # Public AI demo only. The ?demo=true dashboard showcases Bedrock AI via
        # public POSTs to /api/v1/ai/; those, and only those, pass on a demo
        # Referer. The Referer is client-settable and is NOT a security boundary,
        # so it must never gate live data. The previous `request.method == "GET"`
        # clause let an anonymous caller read the live registry, telemetry, and
        # alerts just by spoofing this header; it is removed. Live data is
        # reachable only via the session cookie or a Cognito Bearer below.
        referer = request.headers.get("referer", "")
        if "demo=true" in referer and path.startswith("/api/v1/ai/"):
            return await call_next(request)

        # 1. Check session cookie
        session_cookie = request.cookies.get("aevus_session", "")
        if session_cookie and SESSION_TOKEN and secrets.compare_digest(session_cookie, SESSION_TOKEN):
            return await call_next(request)

        # 2. Check Cognito Bearer token
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            claims = _decode_cognito_jwt(auth_header[7:])
            if claims is not None:
                if is_demo_identity(claims) and path not in DEMO_ALLOWED_PATHS:
                    # Synthetic-only identity: never reaches the live registry,
                    # telemetry, alerts, or any other data route, whatever other
                    # credential or query/header it sends alongside.
                    logger.warning("demo_identity_denied_live_route", path=path, method=request.method)
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Demo accounts are limited to the synthetic demo data source"},
                    )
                return await call_next(request)

        # 3. Check API key (header or query param for WebSocket)
        if path.endswith("/ws"):
            key = request.query_params.get("key", "")
        else:
            key = request.headers.get(settings.api_key_header, "")

        if key and secrets.compare_digest(key, settings.api_key):
            return await call_next(request)

        return JSONResponse(status_code=401, content={"detail": "Invalid or missing credentials"})
