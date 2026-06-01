"""Tests for the relay overlay (Task #134/#198 — SCADAPack 470 wiring).

Locks in the safety contract that lets the live SHOP-01 → /ingest → pearl
path exist without endangering the show-back demo:

  * no relay data  → assets untouched (byte-identical pre-overlay behavior)
  * stale relay    → ignored, fall back to registry/simulator
  * fresh relay    → vitals overlaid, source="relay", status derived
  * resolver       → prefers a real-sourced RTU over the seeded sim EFM
  * never raises   → a broken relay store degrades, never 500s the dashboard
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.api import relay_overlay
from src.api.relay_overlay import (
    apply_relay_overlay,
    is_real_sourced,
)
from src.models.asset import Asset
from src.models.telemetry import VitalSign


def _asset(asset_id="RTU-01", atype="rtu", vitals=None, status="good"):
    return Asset(
        id=asset_id,
        type=atype,
        status=status,
        name="SCADAPack 470" if asset_id == "RTU-01" else asset_id,
        location="Lab Cabinet",
        vendor="Schneider",
        model="SCADAPack 470",
        vitals=vitals or [],
    )


def _sim_vital(label="BATTERY", raw=13.0):
    return VitalSign(label=label, value=f"{raw}", raw_value=raw, unit="VDC", status="good", source="simulator")


def _set_relay(monkeypatch, data):
    import src.api.ingest as ingest_mod

    monkeypatch.setattr(ingest_mod, "_relay_data", data, raising=False)


def _iso(dt):
    return dt.isoformat()


class TestNoOrStaleRelay:
    def test_no_relay_data_untouched(self, monkeypatch):
        _set_relay(monkeypatch, {})
        a = _asset(vitals=[_sim_vital()])
        out = apply_relay_overlay([a])
        assert out[0].vitals[0].source == "simulator"
        assert out[0].vitals[0].label == "BATTERY"

    def test_stale_relay_ignored(self, monkeypatch):
        old = datetime.now(UTC) - timedelta(seconds=relay_overlay.RELAY_FRESH_SECONDS + 60)
        _set_relay(
            monkeypatch,
            {"RTU-01": {"vitals": {"MODBUS LATENCY": 8}, "timestamp": _iso(old), "relay": True}},
        )
        a = _asset(vitals=[_sim_vital()])
        out = apply_relay_overlay([a])
        # still simulator — stale relay must not win
        assert out[0].vitals[0].source == "simulator"

    def test_missing_asset_in_relay_untouched(self, monkeypatch):
        _set_relay(
            monkeypatch,
            {"OTHER-99": {"vitals": {"X": 1}, "timestamp": _iso(datetime.now(UTC)), "relay": True}},
        )
        a = _asset(vitals=[_sim_vital()])
        out = apply_relay_overlay([a])
        assert out[0].vitals[0].source == "simulator"


class TestFreshRelayOverlay:
    def test_fresh_relay_overlays_vitals(self, monkeypatch):
        _set_relay(
            monkeypatch,
            {
                "RTU-01": {
                    "vitals": {
                        "MODBUS LINK": 1,
                        "MODBUS LATENCY": {"value": 8, "unit": "ms", "status": "good"},
                        "COMM SUCCESS": {"value": 100, "unit": "%"},
                    },
                    "timestamp": _iso(datetime.now(UTC)),
                    "relay": True,
                }
            },
        )
        a = _asset(vitals=[_sim_vital()])
        out = apply_relay_overlay([a])[0]
        labels = {v.label for v in out.vitals}
        assert labels == {"MODBUS LINK", "MODBUS LATENCY", "COMM SUCCESS"}
        assert all(v.source == "relay" for v in out.vitals)
        assert out.status == "good"

    def test_link_down_sets_bad(self, monkeypatch):
        _set_relay(
            monkeypatch,
            {
                "RTU-01": {
                    "vitals": {"MODBUS LINK": 0, "COMMUNICATION FAULT ALARM": "ACTIVE"},
                    "timestamp": _iso(datetime.now(UTC)),
                    "relay": True,
                }
            },
        )
        out = apply_relay_overlay([_asset()])[0]
        assert out.status == "bad"

    def test_active_alarm_sets_warn(self, monkeypatch):
        _set_relay(
            monkeypatch,
            {
                "RTU-01": {
                    "vitals": {"MODBUS LINK": 1, "HIGH PRESSURE ALARM": "ACTIVE"},
                    "timestamp": _iso(datetime.now(UTC)),
                    "relay": True,
                }
            },
        )
        out = apply_relay_overlay([_asset()])[0]
        assert out.status == "warn"


class TestNeverRaises:
    def test_broken_relay_store_degrades(self, monkeypatch):
        import src.api.ingest as ingest_mod

        # _relay_data that explodes on .get()
        class Boom:
            def get(self, *a, **k):
                raise RuntimeError("kaboom")

            def __bool__(self):
                return True

        monkeypatch.setattr(ingest_mod, "_relay_data", Boom(), raising=False)
        a = _asset(vitals=[_sim_vital()])
        out = apply_relay_overlay([a])  # must not raise
        assert out[0].vitals[0].source == "simulator"


class TestResolverPreference:
    def test_is_real_sourced(self):
        assert is_real_sourced(_asset(vitals=[VitalSign(label="X", value="1", raw_value=1.0, unit="", source="relay")]))
        assert not is_real_sourced(_asset(vitals=[_sim_vital()]))
        assert not is_real_sourced(_asset(vitals=[]))

    def test_find_efm_rtu_prefers_real_rtu_over_sim_efm(self):
        from src.api.pearls import _find_efm_rtu

        sim_efm = _asset(asset_id="EFM-01", atype="efm", vitals=[_sim_vital()])
        real_rtu = _asset(
            asset_id="RTU-01",
            atype="rtu",
            vitals=[VitalSign(label="MODBUS LINK", value="1", raw_value=1.0, unit="", source="relay")],
        )
        # EFM listed first (as in production) — resolver must still pick the real RTU
        assert _find_efm_rtu([sim_efm, real_rtu]).id == "RTU-01"

    def test_find_efm_rtu_falls_back_to_first_when_no_real(self):
        from src.api.pearls import _find_efm_rtu

        sim_efm = _asset(asset_id="EFM-01", atype="efm", vitals=[_sim_vital()])
        sim_rtu = _asset(asset_id="RTU-01", atype="rtu", vitals=[_sim_vital()])
        # No real source → preserve pre-existing behavior (first rtu)
        assert _find_efm_rtu([sim_efm, sim_rtu]).id == "RTU-01"
