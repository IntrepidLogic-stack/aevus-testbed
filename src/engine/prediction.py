"""
Aevus Testbed --- Prediction Engine
Analyzes InfluxDB time-series data to detect anomalies and predict failures.

Techniques:
  - Rolling z-score: flags readings that deviate >2σ from recent history
  - Linear trend extrapolation: estimates time until a metric crosses a threshold
  - Multi-metric risk aggregation: combines per-metric risks into asset risk score

The engine runs periodically (default: every 60s) and updates the prediction
store, which is served by the /api/v1/predictions endpoint.
"""

from __future__ import annotations

import math
from datetime import datetime

import structlog

from src.models.prediction import Prediction
from src.storage.influx import InfluxStorage

logger = structlog.get_logger()

# Metrics to analyze per device type
MONITORED_METRICS: dict[str, list[dict]] = {
    "radio": [
        {"metric": "rssi", "direction": "lower_bad", "warn": -80, "crit": -90, "unit": "dBm"},
        {"metric": "snr", "direction": "lower_bad", "warn": 15, "crit": 10, "unit": "dB"},
        {"metric": "temperature", "direction": "upper_bad", "warn": 60, "crit": 75, "unit": "°C"},
        {
            "metric": "error_packets",
            "direction": "upper_bad",
            "warn": 500,
            "crit": 2000,
            "unit": "count",
        },
    ],
    "rtu": [
        {
            "metric": "suction_pressure",
            "direction": "upper_bad",
            "warn": 800,
            "crit": 900,
            "unit": "PSI",
        },
        {
            "metric": "discharge_pressure",
            "direction": "upper_bad",
            "warn": 1200,
            "crit": 1400,
            "unit": "PSI",
        },
        {
            "metric": "battery_voltage",
            "direction": "lower_bad",
            "warn": 12.0,
            "crit": 11.5,
            "unit": "VDC",
        },
        {"metric": "vibration", "direction": "upper_bad", "warn": 4.5, "crit": 7.1, "unit": "mm/s"},
    ],
    "router": [
        {"metric": "cpu_load", "direction": "upper_bad", "warn": 70, "crit": 90, "unit": "%"},
        {
            "metric": "if_in_errors",
            "direction": "upper_bad",
            "warn": 100,
            "crit": 1000,
            "unit": "count",
        },
    ],
    "switch": [
        {"metric": "cpu_load", "direction": "upper_bad", "warn": 70, "crit": 90, "unit": "%"},
    ],
}

# Analysis windows
HISTORY_HOURS = 4  # How far back to query for anomaly detection
TREND_HOURS = 2  # Window for trend extrapolation
MIN_POINTS = 6  # Minimum data points needed for analysis
Z_SCORE_WARN = 2.0  # Standard deviations for warning
Z_SCORE_CRIT = 3.0  # Standard deviations for critical


class PredictionEngine:
    """Analyzes telemetry trends and predicts failures."""

    def __init__(self, influx: InfluxStorage) -> None:
        self.influx = influx
        self._predictions: dict[str, Prediction] = {}  # asset_id -> latest prediction
        self.log = logger.bind(component="prediction")

    @property
    def predictions(self) -> list[Prediction]:
        """Return all current predictions sorted by risk score descending."""
        return sorted(self._predictions.values(), key=lambda p: p.risk_score, reverse=True)

    def get_prediction(self, asset_id: str) -> Prediction | None:
        """Get the current prediction for a specific asset."""
        return self._predictions.get(asset_id)

    async def analyze_asset(
        self,
        asset_id: str,
        asset_name: str,
        asset_type: str,
        location: str = "Lab Cabinet",
    ) -> Prediction | None:
        """Run full prediction analysis for a single asset.

        Queries InfluxDB for recent metric history, computes anomaly scores
        and trend-based time-to-failure estimates, then aggregates into a
        single risk score.

        Returns a Prediction if risk > 0, else None.
        """
        metric_defs = MONITORED_METRICS.get(asset_type, [])
        if not metric_defs:
            return None

        metric_risks: list[dict] = []
        drivers: list[str] = []
        min_ttf_hours: float = float("inf")

        for mdef in metric_defs:
            result = self._analyze_metric(
                asset_id=asset_id,
                metric=mdef["metric"],
                direction=mdef["direction"],
                warn_threshold=mdef["warn"],
                crit_threshold=mdef["crit"],
                unit=mdef["unit"],
            )
            if result is None:
                continue

            metric_risks.append(result)

            if result["risk"] > 30:
                drivers.append(result["driver_label"])

            if result["ttf_hours"] is not None and result["ttf_hours"] < min_ttf_hours:
                min_ttf_hours = result["ttf_hours"]

        if not metric_risks:
            # No data available yet — remove stale prediction
            self._predictions.pop(asset_id, None)
            return None

        # Aggregate: weighted max (worst metric dominates, others contribute)
        risks = [r["risk"] for r in metric_risks]
        max_risk = max(risks)
        avg_risk = sum(risks) / len(risks)
        # 70% worst metric, 30% average of all
        composite_risk = int(round(max_risk * 0.7 + avg_risk * 0.3))
        composite_risk = max(0, min(100, composite_risk))

        # Estimate failure time
        if min_ttf_hours == float("inf"):
            estimated_failure = "No trend detected"
            confidence_interval = "—"
        elif min_ttf_hours <= 0:
            estimated_failure = "Imminent"
            confidence_interval = "< 1 hour"
        elif min_ttf_hours < 24:
            hours = max(1, int(min_ttf_hours))
            estimated_failure = f"{hours} hours"
            low = max(1, int(min_ttf_hours * 0.6))
            high = int(min_ttf_hours * 1.5) + 1
            confidence_interval = f"{low}-{high} hours"
        else:
            days = max(1, int(min_ttf_hours / 24))
            estimated_failure = f"{days} days"
            low = max(1, int(days * 0.6))
            high = int(days * 1.5) + 1
            confidence_interval = f"{low}-{high} days"

        if not drivers:
            drivers = ["Within normal parameters"]

        prediction = Prediction(
            asset_id=asset_id,
            asset_name=asset_name,
            asset_type=asset_type,
            location=location,
            risk_score=composite_risk,
            estimated_failure=estimated_failure,
            confidence_interval=confidence_interval,
            primary_drivers=drivers[:5],  # Top 5 drivers
        )

        self._predictions[asset_id] = prediction

        self.log.info(
            "prediction_updated",
            asset=asset_id,
            risk=composite_risk,
            ttf=estimated_failure,
            drivers=drivers,
        )

        return prediction

    def _analyze_metric(
        self,
        asset_id: str,
        metric: str,
        direction: str,
        warn_threshold: float,
        crit_threshold: float,
        unit: str,
    ) -> dict | None:
        """Analyze a single metric for anomalies and trends.

        Returns a dict with:
          - risk: 0-100 risk contribution
          - ttf_hours: estimated hours to threshold breach (or None)
          - driver_label: human-readable description if risk > 0
        """
        # Query InfluxDB for recent data
        data = self.influx.query_trend(asset_id, metric, hours=HISTORY_HOURS)
        if not data or len(data) < MIN_POINTS:
            return None

        values = [d["value"] for d in data if d["value"] is not None]
        if len(values) < MIN_POINTS:
            return None

        # ── Statistical analysis ──
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = math.sqrt(variance) if variance > 0 else 0.001
        latest = values[-1]

        # Z-score of latest reading
        z_score = abs(latest - mean) / std

        # ── Trend analysis (linear regression on recent window) ──
        recent_count = min(len(values), max(MIN_POINTS, len(values) // 2))
        recent = values[-recent_count:]
        slope = self._linear_slope(recent)

        # ── Time-to-failure estimation ──
        ttf_hours: float | None = None
        threshold_target = crit_threshold  # Predict time to critical

        if direction == "upper_bad" and slope > 0:
            # Value rising toward threshold
            gap = threshold_target - latest
            if gap > 0:
                # Estimate data point interval from timestamps
                interval_hours = self._estimate_interval_hours(data)
                points_to_threshold = gap / slope if slope > 0 else float("inf")
                ttf_hours = points_to_threshold * interval_hours
            else:
                ttf_hours = 0  # Already past threshold
        elif direction == "lower_bad" and slope < 0:
            # Value falling toward threshold
            gap = latest - threshold_target
            if gap > 0:
                interval_hours = self._estimate_interval_hours(data)
                points_to_threshold = gap / abs(slope) if slope != 0 else float("inf")
                ttf_hours = points_to_threshold * interval_hours
            else:
                ttf_hours = 0

        # ── Risk score calculation ──
        risk = 0.0

        # Component 1: Proximity to threshold (0-40 points)
        if direction == "upper_bad":
            range_span = crit_threshold - warn_threshold
            if range_span > 0:
                proximity = (latest - warn_threshold) / range_span
                proximity = max(0, min(1, proximity))
                risk += proximity * 40
        elif direction == "lower_bad":
            range_span = warn_threshold - crit_threshold
            if range_span > 0:
                proximity = (warn_threshold - latest) / range_span
                proximity = max(0, min(1, proximity))
                risk += proximity * 40

        # Component 2: Z-score anomaly (0-30 points)
        if z_score > Z_SCORE_WARN:
            z_risk = min(1.0, (z_score - Z_SCORE_WARN) / (Z_SCORE_CRIT - Z_SCORE_WARN))
            risk += z_risk * 30

        # Component 3: Adverse trend (0-30 points)
        if ttf_hours is not None and ttf_hours < 168:  # < 7 days
            if ttf_hours <= 0:
                risk += 30
            elif ttf_hours < 6:
                risk += 25
            elif ttf_hours < 24:
                risk += 20
            elif ttf_hours < 72:
                risk += 15
            else:
                risk += 8

        risk = int(round(max(0, min(100, risk))))

        # Build driver label
        driver_parts = []
        if z_score > Z_SCORE_WARN:
            driver_parts.append(f"anomalous reading (z={z_score:.1f})")
        if ttf_hours is not None and ttf_hours < 72:
            driver_parts.append("adverse trend")
        if risk > 30:
            if direction == "upper_bad":
                driver_parts.append(f"{metric.replace('_', ' ')} elevated ({latest:.1f} {unit})")
            else:
                driver_parts.append(f"{metric.replace('_', ' ')} degraded ({latest:.1f} {unit})")

        driver_label = (
            "; ".join(driver_parts) if driver_parts else f"{metric.replace('_', ' ')} nominal"
        )

        return {
            "risk": risk,
            "ttf_hours": ttf_hours,
            "driver_label": driver_label.capitalize(),
            "z_score": z_score,
            "slope": slope,
            "latest": latest,
        }

    @staticmethod
    def _linear_slope(values: list[float]) -> float:
        """Compute the slope of a simple linear regression.

        Uses index as x-axis (0, 1, 2, ...).
        Returns the change in value per data point.
        """
        n = len(values)
        if n < 2:
            return 0.0

        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n

        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0.0

        return numerator / denominator

    @staticmethod
    def _estimate_interval_hours(data: list[dict]) -> float:
        """Estimate the average time interval between data points in hours."""
        if len(data) < 2:
            return 1.0 / 12  # Default: 5 minutes

        try:
            first_time = datetime.fromisoformat(data[0]["time"].replace("Z", "+00:00"))
            last_time = datetime.fromisoformat(data[-1]["time"].replace("Z", "+00:00"))
            span = (last_time - first_time).total_seconds()
            if span <= 0:
                return 1.0 / 12
            intervals = len(data) - 1
            return (span / intervals) / 3600.0
        except (KeyError, ValueError):
            return 1.0 / 12
