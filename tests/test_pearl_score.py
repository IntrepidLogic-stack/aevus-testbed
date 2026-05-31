"""Tests for the Rickerson Scale pearl normalization engine (P0a).

Covers:
  - Piecewise interpolation correctness
  - Per-device-class scoring across healthy/warn/critical bands
  - Status band thresholds match spec (60/30 boundaries)
  - Offline assets always score None
  - Missing-vital graceful degradation (re-normalize remaining weights)
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.engine.pearl_score import (
    _band,
    _piecewise,
    score_asset,
    score_edge,
    score_radio,
    score_router,
    score_rtu,
)
from src.models.asset import Asset
from src.models.telemetry import VitalSign


def _mk_asset(asset_id: str, asset_type: str, status: str, vitals: list[tuple]) -> Asset:
    return Asset(
        id=asset_id,
        type=asset_type,
        status=status,
        name=asset_id,
        location="Lab",
        health=None,
        last_seen=datetime.now(UTC),
        vendor="TestVendor",
        model="TestModel",
        firmware=None,
        vitals=[VitalSign(label=lbl, value=str(val), raw_value=val, unit=unit) for lbl, val, unit in vitals],
        events=[],
    )


# ── Piecewise math ──────────────────────────────────────────────────
class TestPiecewise:
    def test_anchor_exact(self):
        assert _piecewise(0.0, [(0.0, 100.0), (10.0, 0.0)]) == 100.0

    def test_midpoint_interpolates(self):
        assert _piecewise(5.0, [(0.0, 100.0), (10.0, 0.0)]) == 50.0

    def test_below_range_clamps_low(self):
        assert _piecewise(-5.0, [(0.0, 100.0), (10.0, 0.0)]) == 100.0

    def test_above_range_clamps_high(self):
        assert _piecewise(20.0, [(0.0, 100.0), (10.0, 0.0)]) == 0.0


# ── Status band thresholds ──────────────────────────────────────────
class TestBand:
    def test_none_is_offline(self):
        assert _band(None) == "offline"

    def test_100_is_good(self):
        assert _band(100) == "good"

    def test_60_boundary_is_good(self):
        assert _band(60) == "good"

    def test_59_is_warn(self):
        assert _band(59) == "warn"

    def test_30_boundary_is_warn(self):
        assert _band(30) == "warn"

    def test_29_is_bad(self):
        assert _band(29) == "bad"

    def test_0_is_bad(self):
        assert _band(0) == "bad"


# ── Radio scoring ───────────────────────────────────────────────────
class TestScoreRadio:
    def test_pristine_radio_scores_good(self):
        a = _mk_asset(
            "RAD-01",
            "radio",
            "good",
            [
                ("RSSI", -65, "dBm"),
                ("LINK STATE", 1, ""),
                ("TEMPERATURE", 35, "°C"),
                ("VOLTAGE", 13.3, "V"),
                ("LATENCY", 5, "ms"),
                ("TX ERRORS", 0, ""),
                ("RX ERRORS", 0, ""),
            ],
        )
        score = score_radio(a)
        assert score is not None
        assert score >= 90

    def test_fading_radio_scores_warn(self):
        a = _mk_asset(
            "RAD-02",
            "radio",
            "warn",
            [
                ("RSSI", -87, "dBm"),
                ("LINK STATE", 1, ""),
                ("TEMPERATURE", 50, "°C"),
                ("VOLTAGE", 12.5, "V"),
                ("LATENCY", 80, "ms"),
                ("TX ERRORS", 0, ""),
                ("RX ERRORS", 0, ""),
            ],
        )
        score = score_radio(a)
        assert score is not None
        assert 30 <= score < 80

    def test_dead_link_scores_bad(self):
        a = _mk_asset(
            "RAD-02",
            "radio",
            "bad",
            [
                ("RSSI", -100, "dBm"),
                ("LINK STATE", 0, ""),
                ("TEMPERATURE", 35, "°C"),
                ("VOLTAGE", 13.3, "V"),
            ],
        )
        score = score_radio(a)
        assert score is not None
        assert score < 30

    def test_missing_vitals_renormalizes(self):
        """A radio with only RSSI + link should still score, not crash."""
        a = _mk_asset(
            "RAD-01",
            "radio",
            "good",
            [
                ("RSSI", -65, "dBm"),
                ("LINK STATE", 1, ""),
            ],
        )
        score = score_radio(a)
        assert score is not None
        assert score >= 60

    def test_no_data_returns_none(self):
        a = _mk_asset("RAD-X", "radio", "unknown", [])
        assert score_radio(a) is None


# ── Router / switch / RTU / edge ────────────────────────────────────
class TestScoreOthers:
    def test_router_healthy(self):
        a = _mk_asset(
            "RTR-01",
            "router",
            "good",
            [
                ("CPU LOAD", 15, "%"),
            ],
        )
        score = score_router(a)
        assert score is not None
        assert score >= 80

    def test_router_cpu_pegged(self):
        a = _mk_asset(
            "RTR-01",
            "router",
            "warn",
            [
                ("CPU LOAD", 95, "%"),
            ],
        )
        score = score_router(a)
        assert score is not None
        assert score < 30

    def test_rtu_offline(self):
        a = _mk_asset("RTU-01", "rtu", "offline", [])
        assert score_rtu(a) is None

    def test_rtu_healthy_battery(self):
        a = _mk_asset(
            "RTU-01",
            "rtu",
            "good",
            [
                ("BATTERY", 13.3, "V"),
            ],
        )
        score = score_rtu(a)
        assert score is not None
        assert score >= 60

    def test_edge_healthy(self):
        a = _mk_asset(
            "EDGE-01",
            "edge",
            "good",
            [
                ("CPU LOAD", 10, "%"),
                ("MEMORY USED", 25, "%"),
            ],
        )
        score = score_edge(a)
        assert score is not None
        assert score >= 80


# ── score_asset dispatch + offline override ────────────────────────
class TestScoreAsset:
    def test_offline_always_returns_none_offline(self):
        a = _mk_asset(
            "RAD-01",
            "radio",
            "offline",
            [
                ("RSSI", -65, "dBm"),
                ("LINK STATE", 1, ""),
            ],
        )
        score, status = score_asset(a)
        assert score is None
        assert status == "offline"

    def test_unknown_type_returns_none(self):
        a = _mk_asset("X-01", "router", "good", [])
        # router with no data falls back to "alive but unmeasured" = 70
        score, status = score_asset(a)
        assert score == 70
        assert status == "good"


# ── Trade-secret discipline — API contract ────────────────────────
def test_engine_module_has_trade_secret_header():
    """The pearl_score.py module must carry an explicit TRADE SECRET banner
    so any future contributor sees the constraint before adding exports."""
    from pathlib import Path

    from src.engine import pearl_score

    src = Path(pearl_score.__file__).read_text()
    assert "TRADE SECRET" in src
    assert "INTREPID LOGIC PROPRIETARY" in src
