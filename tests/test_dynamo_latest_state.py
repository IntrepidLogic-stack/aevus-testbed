"""Tests for the Phase 2 DynamoDB latest-state reader.

Exercises the pure item→latest transform + the overlay-only enrich(), without
boto3 (the network query is separated from the transform on purpose).
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.models.asset import Asset
from src.storage.dynamo_latest_state import DynamoLatestStateReader


def _reader() -> DynamoLatestStateReader:
    return DynamoLatestStateReader(table_name="t", region="us-east-1")


def _asset(**over) -> Asset:
    base = {
        "id": "RAD-01",
        "type": "radio",
        "status": "unknown",
        "name": "Trio JR900 #1",
        "location": "Lab",
        "health": None,
        "last_seen": datetime.now(UTC),
        "vendor": "Trio",
        "model": "JR900",
        "vitals": [],
        "events": [],
    }
    base.update(over)
    return Asset(**base)


class TestItemsToLatest:
    def test_telemetry_items_become_vitals(self):
        items = [
            {"metric": "rssi", "value": -143, "unit": "dBm", "source": "snmp"},
            {"metric": "voltage", "value": 13.3, "unit": "V", "source": "snmp"},
        ]
        latest = _reader()._items_to_latest("RAD-01", items)
        assert len(latest.vitals) == 2
        # normalize_batch should produce labelled vitals carrying the source
        assert all(v.source == "snmp" for v in latest.vitals)
        assert latest.state == {}

    def test_state_items_become_state_dict(self):
        items = [
            {"metric": "state:firmware", "value": "3.8.4 Build 4104", "source": "edge"},
            {"metric": "state:status", "value": "warn", "source": "edge"},
            {"metric": "state:health", "value": "76", "source": "edge"},
        ]
        latest = _reader()._items_to_latest("RAD-01", items)
        assert latest.vitals == []
        assert latest.state["firmware"] == "3.8.4 Build 4104"
        assert latest.state["status"] == "warn"
        assert latest.state["health"] == "76"

    def test_mixed_and_bad_values_skipped(self):
        items = [
            {"metric": "rssi", "value": -143, "unit": "dBm", "source": "snmp"},
            {"metric": "state:firmware", "value": "v1", "source": "edge"},
            {"metric": "broken", "value": "not-a-number", "unit": "x", "source": "snmp"},
            {"metric": "", "value": 1},  # empty metric → skipped
        ]
        latest = _reader()._items_to_latest("RAD-01", items)
        assert len(latest.vitals) == 1  # only rssi; broken + empty skipped
        assert latest.state == {"firmware": "v1"}


class TestEnrich:
    def test_enrich_overlays_state_and_vitals(self, monkeypatch):
        from src.models.telemetry import VitalSign
        from src.storage.dynamo_latest_state import AssetLatest

        r = _reader()
        fake = AssetLatest(
            vitals=[VitalSign(label="RSSI", value="-143 dBm", raw_value=-143.0, unit="dBm", source="snmp")],
            state={"firmware": "3.8.4 Build 4104", "status": "warn", "health": "76"},
        )
        monkeypatch.setattr(r, "fetch", lambda asset_id: fake)

        a = _asset()
        r.enrich(a)
        assert a.firmware == "3.8.4 Build 4104"
        assert a.status == "warn"
        assert a.health == 76
        assert len(a.vitals) == 1 and a.vitals[0].label == "RSSI"

    def test_enrich_empty_does_not_blank_asset(self, monkeypatch):
        from src.storage.dynamo_latest_state import AssetLatest

        r = _reader()
        monkeypatch.setattr(r, "fetch", lambda asset_id: AssetLatest())

        a = _asset(firmware="orig-fw", status="good", health=91)
        r.enrich(a)
        # Overlay-only: empty Dynamo result must not wipe registry data.
        assert a.firmware == "orig-fw"
        assert a.status == "good"
        assert a.health == 91
