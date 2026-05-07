"""Tests for the FastAPI endpoints and auth middleware."""

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
def auth_client():
    """Test client with API key enforcement."""
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = "test-secret-key"
        mock_settings.api_key_header = "X-API-Key"
        with TestClient(app) as c:
            yield c


class TestDashboard:
    def test_root_serves_dashboard(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_root_no_api_key_needed(self, auth_client):
        """Dashboard should not require API key."""
        resp = auth_client.get("/")
        assert resp.status_code == 200


class TestAssetsAPI:
    def test_list_assets(self, client):
        resp = client.get("/api/v1/assets")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_asset_not_found(self, client):
        resp = client.get("/api/v1/assets/NONEXISTENT")
        assert resp.status_code == 404


class TestAlertsAPI:
    def test_list_alerts(self, client):
        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestHealthAPI:
    def test_health_summary(self, client):
        resp = client.get("/api/v1/health/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_assets" in data
        assert "avg_health" in data


class TestDiagnosticsAPI:
    def test_fleet(self, client):
        resp = client.get("/api/v1/diagnostics/fleet")
        assert resp.status_code == 200

    def test_signals(self, client):
        resp = client.get("/api/v1/diagnostics/signals")
        assert resp.status_code == 200


class TestPredictionsAPI:
    def test_predictions(self, client):
        resp = client.get("/api/v1/predictions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestAPIKeyAuth:
    def test_no_key_returns_401(self, auth_client):
        resp = auth_client.get("/api/v1/assets")
        assert resp.status_code == 401

    def test_wrong_key_returns_401(self, auth_client):
        resp = auth_client.get("/api/v1/assets", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_correct_key_returns_200(self, auth_client):
        resp = auth_client.get("/api/v1/assets", headers={"X-API-Key": "test-secret-key"})
        assert resp.status_code == 200

    def test_dashboard_bypasses_auth(self, auth_client):
        resp = auth_client.get("/")
        assert resp.status_code == 200
