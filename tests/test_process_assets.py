"""Tests for the flag-gated derived process-equipment overlay (CMP from RTU-01).

Mirrors the safety contract of reference_assets: OFF by default, never touches the
registry/seed, never raises into the endpoint.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from src.api import process_assets as pa
from src.models.asset import Asset
from src.models.telemetry import VitalSign


def _vital(label: str, status: str, val: float = 1.0, unit: str = "") -> VitalSign:
    return VitalSign(label=label, value=f"{val}{unit}", raw_value=val, unit=unit, status=status)


def _rtu(vitals: list[VitalSign]) -> Asset:
    return Asset(
        id="RTU-01",
        type="rtu",
        status="good",
        name="SCADAPack 470",
        location="lab",
        health=90,
        last_seen=datetime.now(UTC),
        vendor="Schneider",
        model="SCADAPack 470",
        protocol="modbus",
        vitals=vitals,
    )


def test_disabled_returns_empty():
    with patch.object(pa, "settings", MagicMock(process_assets_enabled=False)):
        assert pa.process_assets() == []


def test_enabled_derives_cmp_from_rtu_compressor_vitals():
    rtu = _rtu(
        [
            _vital("SUCTION PRESSURE", "good", 245.0, "PSI"),
            _vital("DISCHARGE PRESSURE", "good", 1180.0, "PSI"),
            _vital("VIBRATION", "bad", 8.2, "mm/s"),
            _vital("RSSI", "good", -68.0, "dBm"),  # non-compressor: must be excluded
        ]
    )
    app_state = MagicMock()
    app_state.db.get_asset.return_value = rtu
    with (
        patch.object(pa, "settings", MagicMock(process_assets_enabled=True)),
        patch("src.main.app_state", app_state),
    ):
        out = pa.process_assets()

    assert len(out) == 1
    cmp = out[0]
    assert cmp.id == "CMP"
    assert cmp.protocol == "modbus"
    labels = {v.label for v in cmp.vitals}
    assert labels == {"SUCTION PRESSURE", "DISCHARGE PRESSURE", "VIBRATION"}  # RSSI excluded
    assert cmp.status == "bad"  # worst of the compressor vitals (VIBRATION bad)
    assert cmp.health == 35


def test_enabled_but_no_rtu_returns_empty():
    app_state = MagicMock()
    app_state.db.get_asset.return_value = None
    with (
        patch.object(pa, "settings", MagicMock(process_assets_enabled=True)),
        patch("src.main.app_state", app_state),
    ):
        assert pa.process_assets() == []


def test_enabled_but_rtu_has_no_compressor_vitals_returns_empty():
    rtu = _rtu([_vital("RSSI", "good", -70.0, "dBm")])  # only non-compressor vitals
    app_state = MagicMock()
    app_state.db.get_asset.return_value = rtu
    with (
        patch.object(pa, "settings", MagicMock(process_assets_enabled=True)),
        patch("src.main.app_state", app_state),
    ):
        assert pa.process_assets() == []


def test_never_raises_on_error():
    app_state = MagicMock()
    app_state.db.get_asset.side_effect = RuntimeError("registry down")
    with (
        patch.object(pa, "settings", MagicMock(process_assets_enabled=True)),
        patch("src.main.app_state", app_state),
    ):
        assert pa.process_assets() == []  # swallowed -> []


# ── K-T4 additions: _worst() precedence + explicit empty-list short-circuit ──
#
# Pinned to the CURRENT implementation of _worst() in src/api/process_assets.py:
#
#     def _worst(vitals: list[VitalSign]) -> str:
#         sv = {getattr(v, "status", "") for v in vitals}
#         if "bad" in sv:  return "bad"
#         if "warn" in sv: return "warn"
#         return "good" if vitals else "unknown"
#
# Notes for future readers:
# - "unknown" is NOT a status that the function returns when one of the input
#   vitals carries status="unknown"; it returns "unknown" ONLY when the input
#   list is empty. That matches today's prod behavior. Do not change these
#   assertions without first changing the function in a separate PR (K-T4 is
#   docs+tests only; production code stays untouched).


def test_worst_empty_returns_unknown():
    assert pa._worst([]) == "unknown"


def test_worst_all_good_returns_good():
    vitals = [
        _vital("SUCTION PRESSURE", "good", 245.0, "PSI"),
        _vital("DISCHARGE PRESSURE", "good", 1180.0, "PSI"),
        _vital("VIBRATION", "good", 2.1, "mm/s"),
    ]
    assert pa._worst(vitals) == "good"


def test_worst_warn_plus_good_returns_warn():
    vitals = [
        _vital("SUCTION PRESSURE", "good", 245.0, "PSI"),
        _vital("VIBRATION", "warn", 4.8, "mm/s"),
    ]
    assert pa._worst(vitals) == "warn"


def test_worst_bad_outranks_warn_and_good():
    vitals = [
        _vital("SUCTION PRESSURE", "good", 245.0, "PSI"),
        _vital("DISCHARGE PRESSURE", "warn", 1210.0, "PSI"),
        _vital("VIBRATION", "bad", 8.2, "mm/s"),
    ]
    assert pa._worst(vitals) == "bad"


def test_worst_only_bad_returns_bad():
    assert pa._worst([_vital("VIBRATION", "bad", 8.2, "mm/s")]) == "bad"


def test_worst_unknown_status_does_not_outrank():
    # A VitalSign with status="" (the schema's empty default) goes through the
    # set-membership check without matching bad/warn, so the non-empty branch
    # of _worst() returns "good". This pins the documented behavior: a vital
    # with no explicit status does NOT raise the worst-of-N to "bad" or "warn"
    # for downstream readers.
    vitals = [_vital("RUN HOURS", "", 1234.0, "hours")]
    assert pa._worst(vitals) == "good"


def test_rtu_absent_returns_empty_list_explicitly():
    """Explicit K-T4 pin: when the flag is on but RTU-01 is unavailable,
    process_assets() returns [] and does NOT raise. Complements
    test_enabled_but_no_rtu_returns_empty by asserting both contract halves
    in one place: empty list AND no raise.
    """
    app_state = MagicMock()
    app_state.db.get_asset.return_value = None
    with (
        patch.object(pa, "settings", MagicMock(process_assets_enabled=True)),
        patch("src.main.app_state", app_state),
    ):
        result = pa.process_assets()
    assert isinstance(result, list)
    assert result == []  # exact short-circuit shape, not just "falsy"
