"""The operator command route and its write-semantics engine were removed.

POST /api/v1/commands and src/engine/commander.py carried Modbus write
vocabulary (open_valve, close_valve, start_motor, stop_motor via FC5 and
set_setpoint via FC6). It was simulated, but a platform whose promise is that
the write capability does not exist should not ship the vocabulary. These tests
keep the route, the engine, and the vocabulary from quietly coming back.
"""

from __future__ import annotations

import importlib
import pathlib
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.main import AppState, app

MASTER_KEY = "real-secret-key"
SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

FIELD_WRITE_TOKENS = (
    "open_valve",
    "close_valve",
    "set_setpoint",
    "start_motor",
    "stop_motor",
    "write_single_coil",
    "write_single_register",
    "write_multiple_coils",
    "write_multiple_registers",
    "write_coil",
    "write_register",
    "mask_write_register",
    "readwrite_registers",
    "COMMAND_MAP",
    "Commander",
)
# Modbus write function codes by name: FC5 / FC05, FC6 / FC06, FC15, FC16.
FUNCTION_CODE_RE = re.compile(r"\bFC\s?0?(5|6|15|16)\b", re.IGNORECASE)


def test_no_command_routes_registered():
    paths = [getattr(r, "path", "") for r in app.routes]
    assert not [p for p in paths if p.rstrip("/").endswith("/commands") or "/commands/" in p]


@pytest.mark.parametrize("module", ["src.api.commands", "src.engine.commander", "src.models.command"])
def test_modules_are_gone(module):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_app_state_has_no_commander():
    assert not hasattr(AppState, "commander")
    assert "commander" not in AppState.__init__.__code__.co_names


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/commands"),
        ("GET", "/api/v1/commands/log"),
    ],
)
def test_command_endpoints_return_404_even_with_master_key(method, path):
    """Authenticated with the master key, the route must be 404 (gone), not 200/405."""
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = MASTER_KEY
        mock_settings.api_key_header = "X-API-Key"
        client = TestClient(app)  # no lifespan: pure routing check, no collectors started
        body = {"asset_id": "x", "command": "open_valve", "confirm": True} if method == "POST" else None
        resp = client.request(method, path, json=body, headers={"X-API-Key": MASTER_KEY})
    assert resp.status_code == 404


def test_no_field_write_vocabulary_in_src():
    offenders = []
    for py in SRC.rglob("*.py"):
        text = py.read_text()
        for token in FIELD_WRITE_TOKENS:
            if token in text:
                offenders.append(f"{py.relative_to(SRC.parent)}: {token}")
        if FUNCTION_CODE_RE.search(text):
            offenders.append(f"{py.relative_to(SRC.parent)}: Modbus write function code (FC5/6/15/16)")
    assert not offenders, "field-write vocabulary found in src/:\n  " + "\n  ".join(offenders)
