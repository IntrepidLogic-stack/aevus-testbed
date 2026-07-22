"""Ingest shared-secret gate tests (ARCHITECTURE_REVIEW H3 follow-up).

/ingest is exempt from API-key auth (the relays have no credential), so it
gets its own X-Ingest-Key gate with a phased rollout: OFF (default, open) →
MONITOR (log-only) → ENFORCE (401). These tests pin all three states plus the
misconfig guard (enforced with an empty secret must stay open).
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
    orig = (settings.ingest_secret, settings.ingest_secret_enforced)
    yield
    settings.ingest_secret, settings.ingest_secret_enforced = orig


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
