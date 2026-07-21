"""Tests for API key authentication middleware."""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def unauthed_client():
    """Client with API key enforcement enabled."""
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = "real-secret-key"
        mock_settings.api_key_header = "X-API-Key"
        with TestClient(app) as c:
            yield c


@pytest.fixture
def authed_client():
    """Client with correct API key."""
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = "real-secret-key"
        mock_settings.api_key_header = "X-API-Key"
        with TestClient(app) as c:
            c.headers["X-API-Key"] = "real-secret-key"
            yield c


@pytest.fixture
def no_auth_client():
    """Client with auth disabled (empty key)."""
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = ""
        mock_settings.api_key_header = "X-API-Key"
        with TestClient(app) as c:
            yield c


class TestAuthMiddleware:
    def test_missing_key_returns_401(self, unauthed_client):
        resp = unauthed_client.get("/api/v1/assets")
        assert resp.status_code == 401

    def test_wrong_key_returns_401(self, unauthed_client):
        resp = unauthed_client.get("/api/v1/assets", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401

    def test_correct_key_passes(self, authed_client):
        resp = authed_client.get("/api/v1/assets")
        assert resp.status_code == 200

    def test_health_ping_bypasses_auth(self, unauthed_client):
        resp = unauthed_client.get("/api/v1/health/ping")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_deploy_trigger_bypasses_api_key(self, unauthed_client):
        """Deploy uses its own X-Deploy-Secret, not API key."""
        with patch("src.api.deploy.settings") as ds:
            ds.deploy_secret = "deploy-s3cret"
            resp = unauthed_client.post(
                "/api/v1/deploy/trigger",
                headers={"X-Deploy-Secret": "deploy-s3cret"},
            )
        assert resp.status_code == 200

    def test_empty_api_key_disables_auth(self, no_auth_client):
        resp = no_auth_client.get("/api/v1/assets")
        assert resp.status_code == 200

    def test_valid_session_cookie_passes(self, unauthed_client):
        """Dashboard session cookie should authenticate requests."""
        token = hashlib.sha256(b"aevus-session:real-secret-key").hexdigest()[:48]
        with patch("src.api.auth.SESSION_TOKEN", token):
            unauthed_client.cookies.set("aevus_session", token)
            resp = unauthed_client.get("/api/v1/assets")
        assert resp.status_code == 200

    def test_invalid_session_cookie_rejected(self, unauthed_client):
        """Bad session cookie should not authenticate."""
        unauthed_client.cookies.set("aevus_session", "bad-token-value")
        resp = unauthed_client.get("/api/v1/assets")
        assert resp.status_code == 401


class TestAuthHardening:
    """H3 — closed auth-bypass holes."""

    def test_notes_write_requires_auth(self, unauthed_client):
        """POST /notes was unconditionally exempt — anyone could write operator
        notes. It must now require auth (middleware rejects before the route)."""
        resp = unauthed_client.post("/api/v1/notes", json={})
        assert resp.status_code == 401

    def test_journal_write_requires_auth(self, unauthed_client):
        """POST /journal (the 'immutable' log) must require auth."""
        resp = unauthed_client.post("/api/v1/journal", json={})
        assert resp.status_code == 401

    def test_demo_referer_still_allows_read(self, unauthed_client):
        """The public ?demo=true dashboard's GET reads still work via Referer."""
        resp = unauthed_client.get(
            "/api/v1/assets",
            headers={"referer": "https://aevus.intrepidlogic.io/dashboard/Aevus_Console.html?demo=true"},
        )
        assert resp.status_code == 200

    def test_demo_header_no_longer_bypasses(self, unauthed_client):
        """The spoofable `x-aevus-demo: true` header must NOT bypass auth."""
        resp = unauthed_client.get("/api/v1/assets", headers={"x-aevus-demo": "true"})
        assert resp.status_code == 401

    def test_demo_referer_does_not_allow_writes(self, unauthed_client):
        """Demo mode is read-only — a demo Referer must not authorize a POST
        (except the /ai/* endpoints the demo showcases)."""
        resp = unauthed_client.post(
            "/api/v1/notes",
            json={},
            headers={"referer": "https://aevus.intrepidlogic.io/dashboard/Aevus_Console.html?demo=true"},
        )
        assert resp.status_code == 401
