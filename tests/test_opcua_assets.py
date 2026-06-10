"""Tests for the flag-gated OPC UA Sidecar overlay (opcua_assets).

Mirrors the safety contract of reference_assets/process_assets: OFF by default,
in-memory only, never raises into the endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.api import opcua_assets as oa
from src.models.telemetry import VitalSign


def _vital(label: str, status: str) -> VitalSign:
    return VitalSign(label=label, value="1", raw_value=1.0, unit="", status=status, source="opcua")


@pytest.fixture(autouse=True)
def _reset_snapshot():
    """Each test starts from a clean snapshot and restores it afterward."""
    saved = dict(oa._snap)
    oa._snap.update({"vitals": [], "asset_id": "", "name": "", "last_seen": None, "reachable": False})
    yield
    oa._snap.clear()
    oa._snap.update(saved)


def _populate(vitals, reachable=True, asset_id="OPCUA-PROSYS-REF", name="OPC UA Ref"):
    oa._snap.update(
        {
            "vitals": vitals,
            "asset_id": asset_id,
            "name": name,
            "last_seen": datetime.now(UTC),
            "reachable": reachable,
        }
    )


def test_disabled_returns_empty():
    _populate([_vital("VIBRATION", "good")])  # populated, but flag OFF
    with patch.object(oa, "settings", MagicMock(opcua_enabled=False)):
        assert oa.opcua_assets() == []


def test_enabled_but_no_snapshot_returns_empty():
    with patch.object(oa, "settings", MagicMock(opcua_enabled=True)):
        assert oa.opcua_assets() == []  # enabled, no successful poll yet


def test_enabled_with_snapshot_returns_one_asset():
    _populate([_vital("VIBRATION", "good"), _vital("SUCTION PRESSURE", "warn")])
    with patch.object(oa, "settings", MagicMock(opcua_enabled=True)):
        out = oa.opcua_assets()
    assert len(out) == 1
    a = out[0]
    assert a.id == "OPCUA-PROSYS-REF"
    assert a.protocol == "opcua"
    assert a.type == "sensor"
    assert a.status == "warn"  # worst of good+warn
    assert a.health == 70
    assert len(a.vitals) == 2


def test_unreachable_snapshot_marks_bad():
    _populate([_vital("VIBRATION", "good")], reachable=False)
    with patch.object(oa, "settings", MagicMock(opcua_enabled=True)):
        out = oa.opcua_assets()
    assert out[0].status == "bad"  # stale/unreachable overlay reads bad
    assert out[0].health == 35


def test_never_raises_on_bad_snapshot():
    # last_seen of the wrong type makes Asset(...) construction fail; must degrade to []
    oa._snap.update({"vitals": [_vital("X", "good")], "last_seen": "not-a-datetime", "reachable": True})
    with patch.object(oa, "settings", MagicMock(opcua_enabled=True)):
        assert oa.opcua_assets() == []  # swallowed -> []


def test_worst_precedence():
    assert oa._worst([]) == "unknown"
    assert oa._worst([_vital("a", "good")]) == "good"
    assert oa._worst([_vital("a", "good"), _vital("b", "warn")]) == "warn"
    assert oa._worst([_vital("a", "warn"), _vital("b", "bad")]) == "bad"


async def test_start_poller_is_noop_when_disabled():
    with patch.object(oa, "settings", MagicMock(opcua_enabled=False, opcua_config_path="")):
        await oa.start_opcua_poller()
    assert oa._task is None  # nothing started
