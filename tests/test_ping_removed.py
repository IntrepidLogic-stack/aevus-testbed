"""The client-driven ping diagnostic was removed (security sign-off).

src/api/ping_diag.py let any holder of the shared master key make the cloud host
ping an arbitrary client-supplied target (an internal-network probing primitive
that is also out of step with the observe-only posture). The router is unmounted
and the module deleted; these tests keep it from quietly coming back.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.main import app

MASTER_KEY = "real-secret-key"


def test_no_ping_routes_registered():
    paths = [getattr(r, "path", "") for r in app.routes]
    assert not [p for p in paths if "/diagnostics/ping" in p]


def test_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.api.ping_diag")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/diagnostics/ping/start"),
        ("POST", "/api/v1/diagnostics/ping/stop"),
        ("GET", "/api/v1/diagnostics/ping/results"),
    ],
)
def test_ping_endpoints_return_404_even_with_master_key(method, path):
    """Authenticated with the master key, the route must be 404 (gone), not 200/405."""
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = MASTER_KEY
        mock_settings.api_key_header = "X-API-Key"
        client = TestClient(app)  # no lifespan: pure routing check, no collectors started
        body = {"target": "127.0.0.1"} if method == "POST" else None
        resp = client.request(method, path, json=body, headers={"X-API-Key": MASTER_KEY})
    assert resp.status_code == 404
