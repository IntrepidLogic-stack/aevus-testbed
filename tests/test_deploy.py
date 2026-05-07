"""Tests for /api/v1/deploy/trigger endpoint."""

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


class TestDeployWebhook:
    def test_trigger_missing_secret_header(self, client):
        resp = client.post("/api/v1/deploy/trigger")
        assert resp.status_code == 422  # missing required header

    def test_trigger_wrong_secret(self, client):
        with patch("src.api.deploy.settings") as mock_settings:
            mock_settings.deploy_secret = "correct-secret"
            resp = client.post(
                "/api/v1/deploy/trigger",
                headers={"X-Deploy-Secret": "wrong-secret"},
            )
        assert resp.status_code == 403

    def test_trigger_success(self, client):
        with patch("src.api.deploy.settings") as mock_settings, patch("src.api.deploy._run_deploy") : # noqa: F841
            mock_settings.deploy_secret = "test-deploy-secret"
            resp = client.post(
                "/api/v1/deploy/trigger",
                headers={"X-Deploy-Secret": "test-deploy-secret"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deploy_started"

    def test_trigger_empty_secret_rejected(self, client):
        with patch("src.api.deploy.settings") as mock_settings:
            mock_settings.deploy_secret = ""
            resp = client.post(
                "/api/v1/deploy/trigger",
                headers={"X-Deploy-Secret": ""},
            )
        assert resp.status_code == 403
