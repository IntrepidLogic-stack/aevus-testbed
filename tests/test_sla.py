"""Tests for the /api/v1/sla endpoint (Phase 4C, track 2).

Mirrors the fixture idiom of tests/test_api.py and tests/test_auth.py:
patch src.api.auth.settings to toggle the API-key middleware per-test,
hit the real (local) app_state wiring -- same as the other API tests.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    """Test client without API key enforcement."""
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = ""  # Disable auth for unit tests
        mock_settings.api_key_header = "X-API-Key"
        with TestClient(app) as c:
            yield c


@pytest.fixture
def unauthed_client():
    """Client with API key enforcement enabled, no key presented."""
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = "test-secret-key"
        mock_settings.api_key_header = "X-API-Key"
        with TestClient(app) as c:
            yield c


class TestSlaAPI:
    def test_sla_requires_auth(self, unauthed_client):
        resp = unauthed_client.get("/api/v1/sla")
        assert resp.status_code == 401

    def test_sla_default_window(self, client):
        resp = client.get("/api/v1/sla")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("period", "targets", "basis", "enterprise", "sites", "digest_line", "generated_at"):
            assert key in data
        assert data["basis"] == "incident-derived"
        assert data["targets"]["availability"] == 99.9
        assert data["targets"]["rf_margin_uptime"] == 99.5
        assert isinstance(data["sites"], list)
        assert isinstance(data["digest_line"], str) and data["digest_line"].startswith("SLA (")

    def test_sla_custom_targets_and_window(self, client):
        resp = client.get(
            "/api/v1/sla",
            params={"avail_target": 99.0, "rf_target": 95.0, "from": "2026-09-01T00:00:00Z", "to": "2026-10-01T00:00:00Z"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["targets"]["availability"] == 99.0
        assert data["targets"]["rf_margin_uptime"] == 95.0
        assert data["period"]["from"].startswith("2026-09-01")
        assert data["period"]["to"].startswith("2026-10-01")

    def test_sla_values_are_sane(self, client):
        resp = client.get("/api/v1/sla")
        assert resp.status_code == 200
        ent = resp.json()["enterprise"]

        def _in_range(v):
            return v is None or (0.0 <= v <= 100.0)

        assert _in_range(ent["availability"])
        assert _in_range(ent["rf_margin_uptime"])
        # met-flags are consistent with the targets actually used
        targets = resp.json()["targets"]
        if ent["availability"] is not None:
            assert ent["availability_met"] == (ent["availability"] >= targets["availability"])
        else:
            assert ent["availability_met"] is False
        if ent["rf_margin_uptime"] is not None:
            assert ent["rf_met"] == (ent["rf_margin_uptime"] >= targets["rf_margin_uptime"])
        else:
            assert ent["rf_met"] is False
        assert ent["incidents"] >= 0
        assert ent["links"] >= 0
        # link_failures never exceeds total incidents in scope
        assert 0 <= ent["link_failures"] <= ent["incidents"]
        # mtbf/mttr are either null or non-negative
        assert ent["mtbf_hours"] is None or ent["mtbf_hours"] >= 0
        assert ent["mttr_minutes"] is None or ent["mttr_minutes"] >= 0

        for site in resp.json()["sites"]:
            assert "site" in site
            assert _in_range(site["availability"])
            assert _in_range(site["rf_margin_uptime"])
