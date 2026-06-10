"""Tests for the OPC UA edge→cloud bridge: seed + scheduler registration + dedupe.

The bridge registers the OPC UA collector on the scheduler (so its readings publish
over MQTT to the cloud read-API) and seeds the asset's registry metadata (so the
cloud renders DynamoDB vitals). Both are flag/config gated and fully inert by default.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import src.main as m
from src.collectors.opcua_client import load_opcua_config

_REF = str(Path(__file__).resolve().parents[1] / "config" / "opcua" / "prosys_reference.yaml")


def test_to_seed_asset_shape():
    cfg = load_opcua_config(_REF)
    a = cfg.to_seed_asset()
    assert a.id == "OPCUA-PROSYS-REF"
    assert a.type == "sensor"
    assert a.protocol == "opcua"
    assert a.vitals == []  # vitals arrive from the edge, not seeded


def test_seed_upserts_when_absent():
    db = MagicMock()
    db.get_asset.return_value = None
    app_state = MagicMock()
    app_state.db = db
    with (
        patch.object(m, "settings", MagicMock(opcua_config_path=_REF)),
        patch.object(m, "app_state", app_state),
    ):
        m._seed_opcua_asset()
    db.upsert_asset.assert_called_once()
    assert db.upsert_asset.call_args[0][0].id == "OPCUA-PROSYS-REF"


def test_seed_skips_when_present():
    db = MagicMock()
    db.get_asset.return_value = object()  # already seeded — must NOT rewrite (#97/#98)
    app_state = MagicMock()
    app_state.db = db
    with (
        patch.object(m, "settings", MagicMock(opcua_config_path=_REF)),
        patch.object(m, "app_state", app_state),
    ):
        m._seed_opcua_asset()
    db.upsert_asset.assert_not_called()


def test_seed_noop_without_config():
    db = MagicMock()
    app_state = MagicMock()
    app_state.db = db
    with (
        patch.object(m, "settings", MagicMock(opcua_config_path="")),
        patch.object(m, "app_state", app_state),
    ):
        m._seed_opcua_asset()
    db.get_asset.assert_not_called()  # fully inert


def test_register_collector_off_by_default():
    sched = MagicMock()
    app_state = MagicMock()
    app_state.scheduler = sched
    with (
        patch.object(m, "settings", MagicMock(opcua_enabled=False, opcua_config_path=_REF)),
        patch.object(m, "app_state", app_state),
    ):
        m._register_opcua_collector()
    sched.register.assert_not_called()


def test_register_collector_on_with_config():
    sched = MagicMock()
    app_state = MagicMock()
    app_state.scheduler = sched
    with (
        patch.object(m, "settings", MagicMock(opcua_enabled=True, opcua_config_path=_REF)),
        patch.object(m, "app_state", app_state),
    ):
        m._register_opcua_collector()
    sched.register.assert_called_once()
    assert sched.register.call_args[0][0] == "OPCUA-PROSYS-REF"


def test_register_collector_enabled_but_no_config_is_safe():
    sched = MagicMock()
    app_state = MagicMock()
    app_state.scheduler = sched
    with (
        patch.object(m, "settings", MagicMock(opcua_enabled=True, opcua_config_path="")),
        patch.object(m, "app_state", app_state),
    ):
        m._register_opcua_collector()
    sched.register.assert_not_called()


def test_overlay_dedupes_when_asset_is_seeded():
    from src.api import opcua_assets as oa
    from src.models.telemetry import VitalSign

    saved = dict(oa._snap)
    oa._snap.update(
        {
            "vitals": [VitalSign(label="V", value="1", raw_value=1.0, unit="", status="good")],
            "asset_id": "OPCUA-PROSYS-REF",
            "name": "x",
            "last_seen": datetime.now(UTC),
            "reachable": True,
        }
    )
    app_state = MagicMock()
    app_state.db.get_asset.return_value = object()  # asset IS in the registry → dedupe
    try:
        with (
            patch.object(oa, "settings", MagicMock(opcua_enabled=True)),
            patch("src.main.app_state", app_state),
        ):
            assert oa.opcua_assets() == []  # overlay defers to the registry-seeded asset
    finally:
        oa._snap.clear()
        oa._snap.update(saved)
