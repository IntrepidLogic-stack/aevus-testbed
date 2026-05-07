"""Tests for the prediction engine."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.engine.prediction import PredictionEngine


class TestPredictionEngine:
    """Tests for PredictionEngine."""

    def _make_engine(self, trend_data=None):
        """Create engine with mocked InfluxStorage."""
        influx = MagicMock()
        if trend_data is not None:
            influx.query_trend.return_value = trend_data
        else:
            influx.query_trend.return_value = []
        return PredictionEngine(influx)

    def _make_trend(self, values, interval_minutes=5):
        """Build a fake trend data list from values."""
        now = datetime.now(UTC)
        return [
            {
                "time": (now - timedelta(minutes=interval_minutes * (len(values) - 1 - i))).isoformat(),
                "value": v,
            }
            for i, v in enumerate(values)
        ]

    @pytest.mark.asyncio
    async def test_no_data_returns_none(self):
        engine = self._make_engine(trend_data=[])
        result = await engine.analyze_asset("RAD-01", "Trio JR900 #1", "radio")
        assert result is None

    @pytest.mark.asyncio
    async def test_stable_metrics_low_risk(self):
        """Stable readings near normal should produce low risk."""
        # All metrics get the same mock data, so use values safe for all:
        # RSSI: -50 (good), SNR: -50 would be bad, so use values that are
        # unambiguously safe. We use per-metric mocking via side_effect.
        influx = MagicMock()

        def _trend(asset_id, metric, hours=4):
            safe = {"rssi": -55, "snr": 25, "temperature": 35, "error_packets": 5}
            val = safe.get(metric, 50)
            now = datetime.now(UTC)
            return [
                {"time": (now - timedelta(minutes=5 * (7 - i))).isoformat(), "value": val + (i % 2) * 0.5}
                for i in range(8)
            ]

        influx.query_trend.side_effect = _trend
        engine = PredictionEngine(influx)
        result = await engine.analyze_asset("RAD-01", "Trio JR900 #1", "radio")
        assert result is not None
        assert result.risk_score < 30

    @pytest.mark.asyncio
    async def test_degrading_rssi_higher_risk(self):
        """RSSI trending toward warning threshold should raise risk."""
        influx = MagicMock()

        def _trend(asset_id, metric, hours=4):
            if metric == "rssi":
                vals = [-70, -72, -74, -76, -78, -79, -80, -81]
            elif metric == "snr":
                vals = [25, 25, 24, 25, 25, 24, 25, 25]  # stable good
            elif metric == "temperature":
                vals = [35, 35, 36, 35, 35, 36, 35, 35]  # stable good
            else:
                vals = [5, 6, 5, 5, 6, 5, 5, 5]  # stable low
            now = datetime.now(UTC)
            return [
                {"time": (now - timedelta(minutes=5 * (7 - i))).isoformat(), "value": v} for i, v in enumerate(vals)
            ]

        influx.query_trend.side_effect = _trend
        engine = PredictionEngine(influx)
        result = await engine.analyze_asset("RAD-01", "Trio JR900 #1", "radio")
        assert result is not None
        assert result.risk_score > 15
        # Estimated failure should be near-term given the adverse trend
        assert result.estimated_failure != "No trend detected"

    @pytest.mark.asyncio
    async def test_anomalous_spike_detected(self):
        """A sudden spike should trigger z-score detection."""
        # Stable then sudden spike
        spiked = self._make_trend([35, 34, 35, 36, 35, 34, 35, 72])
        engine = self._make_engine(trend_data=spiked)
        result = await engine.analyze_asset("RAD-01", "Trio JR900 #1", "radio")
        assert result is not None
        assert result.risk_score > 30

    @pytest.mark.asyncio
    async def test_predictions_sorted_by_risk(self):
        """Predictions list should be sorted by risk_score descending."""
        engine = self._make_engine()

        # Manually inject predictions
        from src.models.prediction import Prediction

        engine._predictions["A"] = Prediction(
            asset_id="A",
            asset_name="Low",
            asset_type="radio",
            location="Lab",
            risk_score=10,
            estimated_failure="7 days",
            confidence_interval="5-9 days",
            primary_drivers=["nominal"],
        )
        engine._predictions["B"] = Prediction(
            asset_id="B",
            asset_name="High",
            asset_type="radio",
            location="Lab",
            risk_score=85,
            estimated_failure="2 hours",
            confidence_interval="1-3 hours",
            primary_drivers=["RSSI critical"],
        )

        preds = engine.predictions
        assert len(preds) == 2
        assert preds[0].risk_score == 85
        assert preds[1].risk_score == 10

    @pytest.mark.asyncio
    async def test_rtu_vibration_trend(self):
        """Rising vibration on RTU should flag risk."""
        rising = self._make_trend([2.0, 2.5, 3.0, 3.5, 4.0, 4.2, 4.4, 4.6])
        engine = self._make_engine(trend_data=rising)
        result = await engine.analyze_asset("RTU-01", "SCADAPack 470", "rtu")
        assert result is not None
        assert result.risk_score > 15

    def test_linear_slope_rising(self):
        engine = self._make_engine()
        slope = engine._linear_slope([1, 2, 3, 4, 5])
        assert slope == pytest.approx(1.0)

    def test_linear_slope_flat(self):
        engine = self._make_engine()
        slope = engine._linear_slope([5, 5, 5, 5])
        assert slope == pytest.approx(0.0)

    def test_linear_slope_falling(self):
        engine = self._make_engine()
        slope = engine._linear_slope([10, 8, 6, 4, 2])
        assert slope == pytest.approx(-2.0)

    def test_get_prediction_missing(self):
        engine = self._make_engine()
        assert engine.get_prediction("NONEXISTENT") is None
