"""
Aevus — canonical metric threshold registry.

Single source of truth for the warn/crit limits + direction of every
config-backed metric, seeded from src.config.settings. The normalizer (status
tagging) and the prediction engine (anomaly / trend risk) both key off these,
so a threshold change in .env / config propagates to every engine instead of
drifting across separately-hardcoded copies — the failure mode called out in
docs/ARCHITECTURE_REVIEW_2026-07.md (H2), where prediction re-hardcoded the same
numbers the normalizer read from settings.

Only the SHARED, config-driven limits belong here. Metrics one engine owns —
the normalizer's process/EFM metrics, prediction's `error_packets` count and the
`battery_solar` composite — stay local to that engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import settings


@dataclass(frozen=True)
class Threshold:
    """Warn/crit limits for one metric.

    direction: "lower_bad"  → a value AT or BELOW the limit is worse
               "upper_bad"  → a value AT or ABOVE the limit is worse
    (matches src.engine.normalizer.evaluate_status semantics.)
    """

    warn: float
    crit: float
    direction: str
    unit: str = ""


THRESHOLDS: dict[str, Threshold] = {
    "rssi": Threshold(settings.threshold_rssi_warn, settings.threshold_rssi_crit, "lower_bad", "dBm"),
    "snr": Threshold(settings.threshold_snr_warn, settings.threshold_snr_crit, "lower_bad", "dB"),
    "temperature": Threshold(settings.threshold_radio_temp_warn, settings.threshold_radio_temp_crit, "upper_bad", "°C"),
    "battery_voltage": Threshold(settings.threshold_battery_warn, settings.threshold_battery_crit, "lower_bad", "VDC"),
    "suction_pressure": Threshold(settings.threshold_suction_warn, settings.threshold_suction_crit, "upper_bad", "PSI"),
    "discharge_pressure": Threshold(
        settings.threshold_discharge_warn, settings.threshold_discharge_crit, "upper_bad", "PSI"
    ),
    "vibration": Threshold(settings.threshold_vibration_warn, settings.threshold_vibration_crit, "upper_bad", "mm/s"),
    "cpu_load": Threshold(settings.threshold_cpu_warn, settings.threshold_cpu_crit, "upper_bad", "%"),
    "if_in_errors": Threshold(
        settings.threshold_if_errors_warn, settings.threshold_if_errors_crit, "upper_bad", "count"
    ),
}


def monitored_metric(metric: str) -> dict:
    """Build a prediction-engine metric spec from the registry.

    Returns the same dict shape the prediction engine's MONITORED_METRICS used
    to hardcode ({metric, direction, warn, crit, unit}) — but sourced from the
    single registry so it can't drift from the normalizer's thresholds.
    """
    t = THRESHOLDS[metric]
    return {"metric": metric, "direction": t.direction, "warn": t.warn, "crit": t.crit, "unit": t.unit}
