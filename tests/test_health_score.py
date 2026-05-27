"""Tests for the composite health score engine."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.engine.health_score import (
    _comm_score,
    _maintenance_score,
    _predictive_risk_score,
    _vital_compliance_score,
    compute_health,
    health_status,
)
from src.models.telemetry import VitalSign


def _vital(label: str, status: str) -> VitalSign:
    return VitalSign(label=label, value="0", raw_value=0.0, unit="", status=status)


# ── _comm_score ──


class TestCommScore:
    def test_none_last_seen(self):
        assert _comm_score(None, 30) == 0.0

    def test_fresh_reading(self):
        now = datetime.now(UTC)
        assert _comm_score(now, 30) == 100.0

    def test_within_2x_poll(self):
        now = datetime.now(UTC) - timedelta(seconds=50)
        assert _comm_score(now, 30) == 100.0

    def test_stale_reading(self):
        old = datetime.now(UTC) - timedelta(seconds=700)
        assert _comm_score(old, 30) == 0.0

    def test_degraded_reading(self):
        mid = datetime.now(UTC) - timedelta(seconds=300)
        score = _comm_score(mid, 30)
        assert 0.0 < score < 100.0


# ── _vital_compliance_score ──


class TestVitalComplianceScore:
    def test_all_good(self):
        vitals = [_vital("A", "good"), _vital("B", "good")]
        assert _vital_compliance_score(vitals) == 100.0

    def test_all_bad(self):
        vitals = [_vital("A", "bad"), _vital("B", "bad")]
        assert _vital_compliance_score(vitals) == 0.0

    def test_all_warn(self):
        vitals = [_vital("A", "warn"), _vital("B", "warn")]
        assert _vital_compliance_score(vitals) == 50.0

    def test_mixed(self):
        vitals = [_vital("A", "good"), _vital("B", "bad")]
        assert _vital_compliance_score(vitals) == 50.0

    def test_info_only_returns_100(self):
        vitals = [_vital("A", ""), _vital("B", "")]
        assert _vital_compliance_score(vitals) == 100.0

    def test_empty_returns_100(self):
        assert _vital_compliance_score([]) == 100.0

    def test_mixed_with_info(self):
        vitals = [_vital("A", "good"), _vital("B", ""), _vital("C", "bad")]
        assert _vital_compliance_score(vitals) == 50.0


# ── _predictive_risk_score ──


class TestPredictiveRiskScore:
    def test_none_returns_70(self):
        assert _predictive_risk_score(None) == 70.0

    def test_zero_risk(self):
        assert _predictive_risk_score(0) == 100.0

    def test_full_risk(self):
        assert _predictive_risk_score(100) == 0.0

    def test_mid_risk(self):
        assert _predictive_risk_score(50) == 50.0

    def test_clamped_above(self):
        assert _predictive_risk_score(-10) == 100.0

    def test_clamped_below(self):
        assert _predictive_risk_score(150) == 0.0


# ── _maintenance_score ──


class TestMaintenanceScore:
    def test_default(self):
        assert _maintenance_score() == 80.0

    def test_low_hours(self):
        assert _maintenance_score(run_hours=5000) == 80.0

    def test_medium_hours(self):
        assert _maintenance_score(run_hours=15000) == 75.0

    def test_high_hours(self):
        assert _maintenance_score(run_hours=25000) == 65.0

    def test_very_high_hours(self):
        assert _maintenance_score(run_hours=60000) == 50.0


# ── compute_health ──


class TestComputeHealth:
    def test_perfect_health(self):
        vitals = [_vital("RSSI", "good"), _vital("SNR", "good")]
        now = datetime.now(UTC)
        score = compute_health(vitals, last_seen=now, poll_interval=30, risk_score=0)
        assert score >= 90

    def test_all_bad_vitals(self):
        vitals = [_vital("RSSI", "bad"), _vital("SNR", "bad")]
        now = datetime.now(UTC)
        score = compute_health(vitals, last_seen=now, poll_interval=30)
        assert score < 70

    def test_no_comm(self):
        vitals = [_vital("RSSI", "good")]
        score = compute_health(vitals, last_seen=None, poll_interval=30)
        assert score < 70

    def test_returns_int(self):
        vitals = [_vital("RSSI", "good")]
        now = datetime.now(UTC)
        score = compute_health(vitals, last_seen=now)
        assert isinstance(score, int)

    def test_clamped_0_100(self):
        vitals = [_vital("RSSI", "good")]
        now = datetime.now(UTC)
        score = compute_health(vitals, last_seen=now)
        assert 0 <= score <= 100


# ── health_status ──


class TestHealthStatus:
    def test_good(self):
        assert health_status(95) == "good"
        assert health_status(80) == "good"

    def test_warn(self):
        assert health_status(79) == "warn"
        assert health_status(50) == "warn"

    def test_bad(self):
        assert health_status(49) == "bad"
        assert health_status(1) == "bad"

    def test_unknown_zero(self):
        assert health_status(0) == "unknown"

    def test_unknown_none(self):
        assert health_status(None) == "unknown"
