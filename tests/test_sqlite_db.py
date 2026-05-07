"""Tests for SQLite storage layer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.models.alert import Alert
from src.models.asset import Asset
from src.storage.sqlite_db import SQLiteDB


@pytest.fixture
def db():
    d = SQLiteDB(db_path=":memory:")
    yield d
    d.close()


class TestAssetCRUD:
    def test_upsert_and_get(self, db):
        asset = Asset(
            id="TEST-01", type="router", name="Test Router",
            location="Lab", vendor="Test", model="T1",
            ip_address="10.0.0.1", protocol="snmp", poll_interval=30,
        )
        db.upsert_asset(asset)
        got = db.get_asset("TEST-01")
        assert got is not None
        assert got.name == "Test Router"
        assert got.type == "router"

    def test_list_assets(self, db):
        for i in range(3):
            db.upsert_asset(Asset(
                id=f"A-{i}", type="radio", name=f"Radio {i}",
                location="Lab", vendor="V", model="M",
                ip_address=f"10.0.0.{i}", protocol="snmp", poll_interval=30,
            ))
        assets = db.list_assets()
        assert len(assets) == 3

    def test_get_nonexistent(self, db):
        assert db.get_asset("NOPE") is None

    def test_upsert_updates_existing(self, db):
        asset = Asset(
            id="UPD-01", type="rtu", name="Original",
            location="Lab", vendor="V", model="M",
            ip_address="10.0.0.1", protocol="modbus", poll_interval=60,
        )
        db.upsert_asset(asset)
        asset.health = 88
        asset.status = "warn"
        asset.ip_address = "10.0.0.99"
        db.upsert_asset(asset)
        got = db.get_asset("UPD-01")
        assert got.health == 88
        assert got.status == "warn"
        assert got.ip_address == "10.0.0.99"
        # name is not in ON CONFLICT update set (immutable field)
        assert got.name == "Original"


class TestAlertCRUD:
    def test_save_and_get_alert(self, db):
        alert = Alert(
            id="ALT-TEST01", severity="warning", asset_id="A-1",
            asset_name="Test Asset", message="Test warning",
            detected_at=datetime.now(UTC), status="open",
        )
        db.save_alert(alert)
        got = db.get_alert("ALT-TEST01")
        assert got is not None
        assert got.severity == "warning"
        assert got.status == "open"

    def test_list_alerts_filter_severity(self, db):
        for sev in ["critical", "warning", "warning"]:
            db.save_alert(Alert(
                id=f"ALT-{sev}-{id(sev)}", severity=sev, asset_id="A-1",
                asset_name="Test", message=f"{sev} alert",
                detected_at=datetime.now(UTC), status="open",
            ))
        crits = db.list_alerts(severity="critical")
        assert len(crits) == 1

    def test_list_alerts_filter_status(self, db):
        db.save_alert(Alert(
            id="ALT-OPEN", severity="warning", asset_id="A-1",
            asset_name="T", message="open", detected_at=datetime.now(UTC),
            status="open",
        ))
        db.save_alert(Alert(
            id="ALT-RESOLVED", severity="warning", asset_id="A-1",
            asset_name="T", message="resolved", detected_at=datetime.now(UTC),
            status="resolved",
        ))
        open_alerts = db.list_alerts(status="open")
        assert all(a.status == "open" for a in open_alerts)

    def test_get_nonexistent_alert(self, db):
        assert db.get_alert("NOPE") is None
