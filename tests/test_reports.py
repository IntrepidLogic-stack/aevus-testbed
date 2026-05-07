"""Tests for /api/v1/reports endpoints."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = ""
        mock_settings.api_key_header = "X-API-Key"
        with TestClient(app) as c:
            yield c


class TestReports:
    def test_fleet_health_report(self, client):
        resp = client.get("/api/v1/reports/fleet-health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["report"] == "fleet-health"
        assert "generated_at" in data
        assert "total_assets" in data
        assert isinstance(data["assets"], list)

    def test_fleet_health_report_with_hours(self, client):
        resp = client.get("/api/v1/reports/fleet-health?hours=48")
        assert resp.status_code == 200
        assert resp.json()["period_hours"] == 48

    def test_alert_report(self, client):
        resp = client.get("/api/v1/reports/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["report"] == "alert-history"
        assert "total_alerts" in data
        assert isinstance(data["alerts"], list)

    def test_alert_report_severity_filter(self, client):
        resp = client.get("/api/v1/reports/alerts?severity=critical")
        assert resp.status_code == 200
        assert resp.json()["report"] == "alert-history"
