"""Authorization gate tests for the admin / user-management routes.

APIKeyMiddleware only AUTHENTICATES: it admits any valid session cookie, any
Cognito pool user's bearer, the demo referer (GET), and the shared master
X-API-Key. The admin routes in src/api/access_requests.py must additionally
require a verified Cognito bearer in the "Admin" group (`require_admin`).

These tests drive the real middleware and the real routes with real RS256 JWTs
signed by a throwaway key (the JWKS client is faked, so no network). boto3 is
patched so nothing can reach AWS, and the access-request store is a tmp file.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import access_requests, auth

MASTER_KEY = "real-secret-key"

# (method, path, json body or None, cognito/boto3 call that proves the handler ran)
ADMIN_ROUTES = [
    ("GET", "/api/v1/access-requests", None),
    ("PUT", "/api/v1/access-requests/0001", {"status": "approved", "cognito_create": True}),
    ("GET", "/api/v1/users", None),
    ("PUT", "/api/v1/users/someone/role", {"role": "Viewer"}),
    ("PUT", "/api/v1/users/someone/toggle", None),
    ("DELETE", "/api/v1/users/someone", None),
    ("POST", "/api/v1/users/someone/reset-password", None),
    ("POST", "/api/v1/users/someone/mfa", None),
]
ROUTE_IDS = [f"{m} {p}" for m, p, _ in ADMIN_ROUTES]


@pytest.fixture(scope="module")
def trusted_key():
    """RSA key the fake JWKS client trusts."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def attacker_key():
    """RSA key the JWKS client does NOT trust (forged-signature tokens)."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key, groups: list[str] | None, *, issuer: str | None = None, expires_in: int = 3600) -> str:
    now = int(time.time())
    claims = {
        "sub": "user-sub",
        "iss": issuer or auth.COGNITO_ISSUER,
        "token_use": "id",
        "iat": now,
        "exp": now + expires_in,
    }
    if groups is not None:
        claims["cognito:groups"] = groups
    return jwt.encode(claims, key, algorithm="RS256")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def cognito():
    """Patch boto3 so no handler can reach AWS; expose the mock Cognito client."""
    client = MagicMock(name="cognito-idp")
    client.list_users.return_value = {"Users": []}
    client.admin_list_groups_for_user.return_value = {"Groups": []}
    client.admin_get_user.return_value = {"Enabled": True}
    with patch("boto3.client", return_value=client):
        yield client


@pytest.fixture
def client(trusted_key, cognito, tmp_path, monkeypatch):
    """Real APIKeyMiddleware + real access_requests router, master key enforced."""
    store = tmp_path / "access_requests.json"
    store.write_text(
        '[{"id": "0001", "name": "Pat", "email": "pat@example.com", "role": "viewer", "status": "pending"}]'
    )
    monkeypatch.setattr(access_requests, "DATA_FILE", store)

    # Fake JWKS client: always hands back the trusted public key (no network).
    fake_jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=trusted_key.public_key()))
    monkeypatch.setattr(auth, "_jwk_client", fake_jwks)
    monkeypatch.setattr(auth, "SESSION_TOKEN", "valid-session-token")

    app = FastAPI()
    app.add_middleware(auth.APIKeyMiddleware)
    app.include_router(access_requests.router, prefix="/api/v1")
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = MASTER_KEY
        mock_settings.api_key_header = "X-API-Key"
        with TestClient(app) as c:
            yield c


def _call(client: TestClient, route, headers=None, cookies=None):
    method, path, body = route
    return client.request(method, path, json=body, headers=headers or {}, cookies=cookies or {})


@pytest.mark.parametrize("route", ADMIN_ROUTES, ids=ROUTE_IDS)
class TestAdminRouteGate:
    def test_unauthenticated_is_401(self, client, cognito, route):
        assert _call(client, route).status_code == 401
        assert cognito.method_calls == []

    def test_master_api_key_is_403(self, client, cognito, route):
        resp = _call(client, route, headers={"X-API-Key": MASTER_KEY})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Admin role required"
        assert cognito.method_calls == []

    def test_session_cookie_is_403(self, client, cognito, route):
        resp = _call(client, route, cookies={"aevus_session": "valid-session-token"})
        assert resp.status_code == 403
        assert cognito.method_calls == []

    @pytest.mark.parametrize("groups", [["Viewer"], ["Operator"], ["Viewer", "Operator"], [], None], ids=str)
    def test_non_admin_bearer_is_403(self, client, cognito, trusted_key, route, groups):
        resp = _call(client, route, headers=_bearer(_token(trusted_key, groups)))
        assert resp.status_code == 403
        assert cognito.method_calls == []

    def test_lookalike_group_names_are_403(self, client, cognito, trusted_key, route):
        # Exact, case-sensitive group match: no "admin", "Administrators", "SuperAdmin".
        for g in ("admin", "Administrators", "SuperAdmin", "ADMIN"):
            resp = _call(client, route, headers=_bearer(_token(trusted_key, [g])))
            assert resp.status_code == 403, g
        assert cognito.method_calls == []

    def test_forged_admin_bearer_is_401(self, client, cognito, attacker_key, route):
        # Untrusted signature, no other credential: stopped at the middleware.
        resp = _call(client, route, headers=_bearer(_token(attacker_key, ["Admin"])))
        assert resp.status_code == 401
        assert cognito.method_calls == []

    def test_forged_admin_bearer_with_master_key_is_403(self, client, cognito, attacker_key, route):
        # Middleware admits the master key; require_admin must still verify the
        # bearer itself and refuse a forged Admin claim.
        headers = {"X-API-Key": MASTER_KEY, **_bearer(_token(attacker_key, ["Admin"]))}
        assert _call(client, route, headers=headers).status_code == 403
        assert cognito.method_calls == []

    def test_wrong_issuer_admin_bearer_is_rejected(self, client, cognito, trusted_key, route):
        tok = _token(trusted_key, ["Admin"], issuer="https://evil.example.com/pool")
        assert _call(client, route, headers=_bearer(tok)).status_code == 401
        assert _call(client, route, headers={"X-API-Key": MASTER_KEY, **_bearer(tok)}).status_code == 403
        assert cognito.method_calls == []

    def test_expired_admin_bearer_is_rejected(self, client, cognito, trusted_key, route):
        tok = _token(trusted_key, ["Admin"], expires_in=-60)
        assert _call(client, route, headers=_bearer(tok)).status_code == 401
        assert _call(client, route, headers={"X-API-Key": MASTER_KEY, **_bearer(tok)}).status_code == 403
        assert cognito.method_calls == []

    def test_admin_bearer_gets_through(self, client, cognito, trusted_key, route):
        resp = _call(client, route, headers=_bearer(_token(trusted_key, ["Admin"])))
        assert resp.status_code == 200, resp.text
        assert resp.json() is not None

    def test_admin_among_multiple_groups_gets_through(self, client, cognito, trusted_key, route):
        resp = _call(client, route, headers=_bearer(_token(trusted_key, ["Operator", "Admin"])))
        assert resp.status_code == 200, resp.text


class TestAdminHandlersRunForAdmin:
    """An admin is not just waved past the gate: the handler's work happens."""

    def test_approve_creates_user_and_adds_to_group(self, client, cognito, trusted_key):
        resp = client.put(
            "/api/v1/access-requests/0001",
            json={"status": "approved", "cognito_create": True},
            headers=_bearer(_token(trusted_key, ["Admin"])),
        )
        assert resp.status_code == 200
        cognito.admin_create_user.assert_called_once()
        assert cognito.admin_create_user.call_args.kwargs["Username"] == "pat@example.com"
        cognito.admin_add_user_to_group.assert_called_once()
        assert cognito.admin_add_user_to_group.call_args.kwargs["GroupName"] == "Viewer"

    def test_delete_user_reaches_cognito_only_for_admin(self, client, cognito, trusted_key):
        client.delete("/api/v1/users/someone", headers={"X-API-Key": MASTER_KEY})
        cognito.admin_delete_user.assert_not_called()
        client.delete("/api/v1/users/someone", headers=_bearer(_token(trusted_key, ["Admin"])))
        cognito.admin_delete_user.assert_called_once()


class TestDemoModeCannotReachAdmin:
    def test_spoofed_demo_referer_cannot_read_users_or_requests(self, client, cognito):
        # The demo Referer no longer bypasses auth for live or admin data: an
        # unauthenticated request is rejected at the middleware (401) before it
        # reaches the admin routes. Admin data must not be readable this way.
        for path in ("/api/v1/users", "/api/v1/access-requests"):
            resp = client.get(path, headers={"Referer": "https://aevus.example/console?demo=true"})
            assert resp.status_code == 401, path
        assert cognito.method_calls == []


class TestPublicSignupStaysPublic:
    def test_post_access_request_needs_no_credentials(self, client, cognito):
        resp = client.post(
            "/api/v1/access-requests",
            json={"name": "New Person", "email": "new@example.com", "company": "Acme"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestFailClosedWhenApiKeyUnset:
    def test_dev_mode_middleware_open_but_admin_routes_still_403(self, client, cognito):
        # api_key empty => middleware lets everything through (dev mode).
        # The admin routes must not inherit that openness.
        with patch("src.api.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.api_key_header = "X-API-Key"
            assert client.get("/api/v1/users").status_code == 403
            assert client.delete("/api/v1/users/someone").status_code == 403
        assert cognito.method_calls == []


class TestEveryAdminRouteDeclaresTheDependency:
    """Structural guard: a new route added to access_requests.py without the
    dependency fails here, instead of silently inheriting master-key access."""

    PUBLIC = {("POST", "/access-requests")}

    @staticmethod
    def _requires_admin(route) -> bool:
        def walk(dep) -> bool:
            return dep.call is auth.require_admin or any(walk(d) for d in dep.dependencies)

        return walk(route.dependant)

    def test_every_non_public_route_in_module_is_gated(self):
        seen = set()
        for route in access_requests.router.routes:
            for method in route.methods:
                key = (method, route.path)
                seen.add(key)
                if key in self.PUBLIC:
                    assert not self._requires_admin(route), f"{key} must stay public"
                else:
                    assert self._requires_admin(route), f"{key} is missing Depends(require_admin)"
        assert seen >= self.PUBLIC
        assert len(seen - self.PUBLIC) == len(ADMIN_ROUTES)

    def test_main_app_mounts_them_gated(self):
        from src.main import app

        gated = set()
        for route in app.routes:
            path = getattr(route, "path", "")
            for method in getattr(route, "methods", None) or ():
                if (method, path.removeprefix("/api/v1")) in {
                    (m, p.removeprefix("/api/v1").replace("0001", "{req_id}").replace("someone", "{username}"))
                    for m, p, _ in ADMIN_ROUTES
                }:
                    assert self._requires_admin(route), f"{method} {path} mounted without require_admin"
                    gated.add((method, path))
        assert len(gated) == len(ADMIN_ROUTES)
