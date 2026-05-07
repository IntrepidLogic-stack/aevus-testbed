"""Tests for /api/v1/integrations endpoints."""

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


class TestIntegrations:
    def test_list_integrations(self, client):
        resp = client.get("/api/v1/integrations")
        assert resp.status_code == 200
        data = resp.json()
        assert "integrations" in data
        assert data["total"] >= 1
        ids = [i["id"] for i in data["integrations"]]
        assert "influxdb" in ids

    def test_get_integration_by_id(self, client):
        resp = client.get("/api/v1/integrations/influxdb")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "influxdb"
        assert data["status"] == "active"

    def test_get_integration_not_found(self, client):
        resp = client.get("/api/v1/integrations/nonexistent")
        assert resp.status_code == 404
