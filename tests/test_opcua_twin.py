"""Tests for the OPC UA → twin compressor-stage overlay (Maps page binding)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.api import twin
from src.models.telemetry import VitalSign


def _vital(label, val, unit, status="good"):
    return VitalSign(label=label, value=f"{val}{unit}", raw_value=val, unit=unit, status=status)


def _cmp_asset():
    a = MagicMock()
    a.vitals = [
        _vital("SUCTION PRESSURE", 247.2, "PSI"),
        _vital("DISCHARGE PRESSURE", 1204.8, "PSI", "warn"),
        _vital("GAS TEMP", 98.0, "°F"),
        _vital("VIBRATION", 0.56, "mm/s"),
        _vital("MOTOR CURRENT", 49.1, "A"),
        _vital("COMPRESSOR RPM", 1199.0, "rpm"),
        _vital("OIL PRESSURE", 59.3, "PSI"),
    ]
    return a


def test_overlay_off_by_default():
    with patch("src.config.settings", MagicMock(opcua_enabled=False)):
        assert twin._opcua_compressor_readings() is None


def test_overlay_builds_from_live_vitals():
    app_state = MagicMock()
    app_state.db.get_asset.return_value = _cmp_asset()
    with (
        patch("src.config.settings", MagicMock(opcua_enabled=True)),
        patch("src.main.app_state", app_state),
    ):
        rds = twin._opcua_compressor_readings()
    assert rds is not None
    by = {r.label: r for r in rds}
    assert by["SUCT"].value == 247.2 and by["SUCT"].reg == "40001"
    assert by["DISCH"].value == 1204.8 and by["DISCH"].status == "warn"  # real status carried
    assert by["VIB"].unit == "mm/s" and by["VIB"].reg == "40017"  # the real CWRU vibration
    assert "MOTOR" in by and "OIL" in by  # richer real-data card
    app_state.db.get_asset.assert_called_with("CMP-KILLDEER")


def test_overlay_none_when_asset_absent():
    app_state = MagicMock()
    app_state.db.get_asset.return_value = None
    with (
        patch("src.config.settings", MagicMock(opcua_enabled=True)),
        patch("src.main.app_state", app_state),
    ):
        assert twin._opcua_compressor_readings() is None


def test_overlay_never_raises():
    app_state = MagicMock()
    app_state.db.get_asset.side_effect = RuntimeError("db down")
    with (
        patch("src.config.settings", MagicMock(opcua_enabled=True)),
        patch("src.main.app_state", app_state),
    ):
        assert twin._opcua_compressor_readings() is None  # swallowed -> sim fallback
