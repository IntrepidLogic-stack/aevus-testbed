"""Ingest shared-secret gate tests (ARCHITECTURE_REVIEW H3 follow-up).

/ingest is exempt from API-key auth (the relays have no credential), so it
gets its own X-Ingest-Key gate. Non-production keeps a phased rollout: OFF
(default, open) -> MONITOR (log-only) -> ENFORCE (401). PRODUCTION fails
closed: the secret is required and always enforced, so an unset INGEST_SECRET
rejects every push instead of leaving the endpoint open.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api.ingest import _check_ingest_secret
from src.api.ingest import router as ingest_router
from src.config import settings

SECRET = "test-ingest-secret-123"


@pytest.fixture
def secret_state():
    """Restore the two ingest-secret settings after each test."""
    orig = (
        settings.ingest_secret,
        settings.ingest_secret_enforced,
        settings.environment,
        settings.api_key,
    )
    # Pin a deterministic NON-production baseline regardless of the dev's .env.
    settings.environment = "development"
    settings.api_key = ""
    yield
    (
        settings.ingest_secret,
        settings.ingest_secret_enforced,
        settings.environment,
        settings.api_key,
    ) = orig


class TestCheckIngestSecret:
    def test_off_by_default_accepts_anything(self, secret_state):
        settings.ingest_secret = ""
        settings.ingest_secret_enforced = False
        _check_ingest_secret(None)  # no header
        _check_ingest_secret("whatever")  # even garbage

    def test_misconfig_enforced_without_secret_stays_open(self, secret_state):
        settings.ingest_secret = ""
        settings.ingest_secret_enforced = True
        _check_ingest_secret(None)  # must NOT raise — telemetry keeps flowing

    def test_monitor_mode_accepts_but_does_not_raise(self, secret_state):
        settings.ingest_secret = SECRET
        settings.ingest_secret_enforced = False
        _check_ingest_secret(None)  # missing → logged, accepted
        _check_ingest_secret("wrong")  # mismatch → logged, accepted
        _check_ingest_secret(SECRET)  # match → accepted

    def test_enforced_rejects_missing_and_mismatch(self, secret_state):
        settings.ingest_secret = SECRET
        settings.ingest_secret_enforced = True
        with pytest.raises(HTTPException) as ei:
            _check_ingest_secret(None)
        assert ei.value.status_code == 401
        with pytest.raises(HTTPException):
            _check_ingest_secret("wrong")
        _check_ingest_secret(SECRET)  # correct key passes


class TestIngestEndpoint:
    """Endpoint-level: the gate runs before any ingest side effect."""

    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.include_router(ingest_router, prefix="/api/v1")
        return TestClient(app)

    def _post(self, client, headers=None):
        return client.post(
            "/api/v1/ingest",
            json={"asset_id": "RTU-01", "vitals": {"MODBUS LINK": 1}},
            headers=headers or {},
        )

    def test_open_when_unset(self, secret_state, client):
        settings.ingest_secret = ""
        settings.ingest_secret_enforced = False
        assert self._post(client).status_code == 200

    def test_enforced_401_without_key(self, secret_state, client):
        settings.ingest_secret = SECRET
        settings.ingest_secret_enforced = True
        assert self._post(client).status_code == 401

    def test_enforced_200_with_key(self, secret_state, client):
        settings.ingest_secret = SECRET
        settings.ingest_secret_enforced = True
        r = self._post(client, headers={"X-Ingest-Key": SECRET})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_monitor_200_without_key(self, secret_state, client):
        settings.ingest_secret = SECRET
        settings.ingest_secret_enforced = False
        assert self._post(client).status_code == 200


def _make_production():
    settings.environment = "production"
    settings.ingest_secret_enforced = False  # prod must ignore this flag


class TestIsProduction:
    def test_explicit_production(self, secret_state):
        for v in ("production", "PROD", " Production "):
            settings.environment = v
            assert settings.is_production is True

    def test_explicit_dev_wins_over_api_key(self, secret_state):
        settings.environment = "development"
        settings.api_key = "k"
        assert settings.is_production is False

    def test_unset_env_with_api_key_is_production(self, secret_state):
        settings.environment = ""
        settings.api_key = "k"
        assert settings.is_production is True

    def test_unset_env_no_api_key_is_not_production(self, secret_state):
        settings.environment = ""
        settings.api_key = ""
        assert settings.is_production is False

    def test_env_var_aliases(self, monkeypatch):
        from src.config import Settings

        monkeypatch.setenv("ENV", "production")
        assert Settings(_env_file=None).environment == "production"


class TestProductionFailsClosed:
    def test_unset_secret_rejects_everything(self, secret_state):
        _make_production()
        settings.ingest_secret = ""
        with pytest.raises(HTTPException) as ei:
            _check_ingest_secret(None)
        assert ei.value.status_code == 401
        with pytest.raises(HTTPException):
            _check_ingest_secret("anything")
        with pytest.raises(HTTPException):
            _check_ingest_secret("")

    def test_enforced_flag_not_required(self, secret_state):
        _make_production()
        settings.ingest_secret = SECRET
        with pytest.raises(HTTPException) as ei:
            _check_ingest_secret(None)  # monitor mode does NOT exist in prod
        assert ei.value.status_code == 401
        with pytest.raises(HTTPException):
            _check_ingest_secret("wrong")
        _check_ingest_secret(SECRET)

    def test_non_ascii_header_is_401_not_500(self, secret_state):
        _make_production()
        settings.ingest_secret = SECRET
        with pytest.raises(HTTPException) as ei:
            _check_ingest_secret("k\u00e9y")
        assert ei.value.status_code == 401

    def test_api_key_without_env_still_fails_closed(self, secret_state):
        settings.environment = ""
        settings.api_key = "prod-api-key"
        settings.ingest_secret = ""
        with pytest.raises(HTTPException):
            _check_ingest_secret(None)


class TestProductionEndpoint:
    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.include_router(ingest_router, prefix="/api/v1")
        return TestClient(app)

    def _post(self, client, headers=None):
        return client.post(
            "/api/v1/ingest",
            json={"asset_id": "RTU-01", "vitals": {"MODBUS LINK": 1}},
            headers=headers or {},
        )

    def test_unauthenticated_push_rejected_when_secret_unset(self, secret_state, client):
        _make_production()
        settings.ingest_secret = ""
        assert self._post(client).status_code == 401
        assert self._post(client, headers={"X-Ingest-Key": ""}).status_code == 401

    def test_unauthenticated_push_rejected_when_secret_set(self, secret_state, client):
        _make_production()
        settings.ingest_secret = SECRET
        assert self._post(client).status_code == 401
        assert self._post(client, headers={"X-Ingest-Key": "wrong"}).status_code == 401

    def test_rejected_push_has_no_side_effects(self, secret_state, client):
        from src.api.ingest import get_relay_data

        _make_production()
        settings.ingest_secret = SECRET
        get_relay_data().pop("RTU-SIDEFX", None)
        r = client.post(
            "/api/v1/ingest",
            json={"asset_id": "RTU-SIDEFX", "vitals": {"X": 1}},
        )
        assert r.status_code == 401
        assert "RTU-SIDEFX" not in get_relay_data()

    def test_correct_key_accepted(self, secret_state, client):
        _make_production()
        settings.ingest_secret = SECRET
        r = self._post(client, headers={"X-Ingest-Key": SECRET})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_full_app_middleware_does_not_bypass_gate(self, secret_state):
        """Through the real app (APIKeyMiddleware exempts /ingest from the API
        key), the handler-level secret gate must still 401 in production."""
        from src.main import app

        _make_production()
        settings.ingest_secret = SECRET
        c = TestClient(app)
        body = {"asset_id": "RTU-01", "vitals": {"MODBUS LINK": 1}}
        assert c.post("/api/v1/ingest", json=body).status_code == 401
        assert c.post("/api/v1/ingest", json=body, headers={"X-Ingest-Key": "nope"}).status_code == 401
