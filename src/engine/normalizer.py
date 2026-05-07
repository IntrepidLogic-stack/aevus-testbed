"""
Aevus Testbed --- Telemetry Normalizer
Converts raw collector readings into VitalSign objects with status tagging.

Each metric has thresholds that determine good/warn/bad status.
The normalizer is the bridge between raw numeric telemetry and the
human-readable vitals shown on the dashboard.
"""

from __future__ import annotations

import structlog
from typing import Literal

from src.config import settings
from src.models.telemetry import RawTelemetry, VitalSign

logger = structlog.get_logger()


# Threshold definitions per metric
# direction: "lower_bad" = below threshold is bad (RSSI, SNR, battery)
#            "upper_bad" = above threshold is bad (pressure, temp, vibration)
#            "bool_bad"  = 1.0 means alarm active
THRESHOLD_MAP: dict[str, dict] = {
    # --- Radio (Trio JR900) ---
    "rssi": {
        "direction": "lower_bad",
        "warn": settings.threshold_rssi_warn,      # -80
        "crit": settings.threshold_rssi_crit,       # -90
        "label": "RSSI",
        "fmt": "{:.0f}",
    },
    "snr": {
        "direction": "lower_bad",
        "warn": settings.threshold_snr_warn,        # 15
        "crit": settings.threshold_snr_crit,        # 10
        "label": "SNR",
        "fmt": "{:.1f}",
    },
    "tx_power": {
        "direction": "info",
        "label": "TX POWER",
        "fmt": "{:.1f}",
    },
    "temperature": {
        "direction": "upper_bad",
        "warn": settings.threshold_radio_temp_warn,  # 60
        "crit": settings.threshold_radio_temp_crit,  # 75
        "label": "TEMPERATURE",
        "fmt": "{:.1f}",
    },
    "voltage": {
        "direction": "info",
        "label": "VOLTAGE",
        "fmt": "{:.1f}",
    },
    "rx_packets": {
        "direction": "info",
        "label": "RX PACKETS",
        "fmt": "{:,.0f}",
    },
    "tx_packets": {
        "direction": "info",
        "label": "TX PACKETS",
        "fmt": "{:,.0f}",
    },
    "error_packets": {
        "direction": "info",
        "label": "ERROR PACKETS",
        "fmt": "{:,.0f}",
    },
    "modulation": {
        "direction": "info",
        "label": "MODULATION",
        "fmt": "{}",
    },

    # --- RTU (SCADAPack 470) ---
    "suction_pressure": {
        "direction": "upper_bad",
        "warn": settings.threshold_suction_warn,     # 800
        "crit": settings.threshold_suction_crit,     # 900
        "label": "SUCTION PRESSURE",
        "fmt": "{:.1f}",
    },
    "discharge_pressure": {
        "direction": "upper_bad",
        "warn": settings.threshold_discharge_warn,   # 1200
        "crit": settings.threshold_discharge_crit,   # 1400
        "label": "DISCHARGE PRESSURE",
        "fmt": "{:.1f}",
    },
    "flow_rate": {
        "direction": "info",
        "label": "FLOW RATE",
        "fmt": "{:.2f}",
    },
    "gas_temperature": {
        "direction": "info",
        "label": "GAS TEMP",
        "fmt": "{:.1f}",
    },
    "ambient_temperature": {
        "direction": "info",
        "label": "AMBIENT TEMP",
        "fmt": "{:.1f}",
    },
    "battery_voltage": {
        "direction": "lower_bad",
        "warn": settings.threshold_battery_warn,     # 12.0
        "crit": settings.threshold_battery_crit,     # 11.5
        "label": "BATTERY",
        "fmt": "{:.1f}",
    },
    "solar_voltage": {
        "direction": "info",
        "label": "SOLAR VOLTAGE",
        "fmt": "{:.1f}",
    },
    "tank_level": {
        "direction": "info",
        "label": "TANK LEVEL",
        "fmt": "{:.1f}",
    },
    "vibration": {
        "direction": "upper_bad",
        "warn": settings.threshold_vibration_warn,   # 4.5
        "crit": settings.threshold_vibration_crit,   # 7.1
        "label": "VIBRATION",
        "fmt": "{:.2f}",
    },
    "run_hours": {
        "direction": "info",
        "label": "RUN HOURS",
        "fmt": "{:,.0f}",
    },

    # --- RTU discrete alarms ---
    "compressor_running": {
        "direction": "info",
        "label": "COMPRESSOR",
        "fmt": "{}",
    },
    "high_pressure_alarm": {
        "direction": "bool_bad",
        "label": "HIGH PRESSURE ALARM",
        "fmt": "{}",
    },
    "low_battery_alarm": {
        "direction": "bool_bad",
        "label": "LOW BATTERY ALARM",
        "fmt": "{}",
    },
    "communication_fault": {
        "direction": "bool_bad",
        "label": "COMM FAULT",
        "fmt": "{}",
    },

    # --- Network (MikroTik / Catalyst) ---
    "cpu_load": {
        "direction": "upper_bad",
        "warn": settings.threshold_cpu_warn,         # 70
        "crit": settings.threshold_cpu_crit,         # 90
        "label": "CPU LOAD",
        "fmt": "{:.0f}",
    },
    "memory_usage": {
        "direction": "info",
        "label": "MEMORY",
        "fmt": "{:.0f}",
    },
    "if_in_octets": {
        "direction": "info",
        "label": "RX BYTES",
        "fmt": "{:,.0f}",
    },
    "if_out_octets": {
        "direction": "info",
        "label": "TX BYTES",
        "fmt": "{:,.0f}",
    },
    "if_in_errors": {
        "direction": "upper_bad",
        "warn": settings.threshold_if_errors_warn,   # 100
        "crit": settings.threshold_if_errors_crit,   # 1000
        "label": "RX ERRORS",
        "fmt": "{:,.0f}",
    },
    "if_out_errors": {
        "direction": "upper_bad",
        "warn": settings.threshold_if_errors_warn,
        "crit": settings.threshold_if_errors_crit,
        "label": "TX ERRORS",
        "fmt": "{:,.0f}",
    },
}


def evaluate_status(
    value: float,
    direction: str,
    warn: float | None = None,
    crit: float | None = None,
) -> Literal["good", "warn", "bad", ""]:
    """Determine status based on value, direction, and thresholds."""
    if direction == "info":
        return ""
    if direction == "bool_bad":
        return "bad" if value >= 1.0 else "good"
    if warn is None or crit is None:
        return ""

    if direction == "lower_bad":
        if value <= crit:
            return "bad"
        if value <= warn:
            return "warn"
        return "good"

    if direction == "upper_bad":
        if value >= crit:
            return "bad"
        if value >= warn:
            return "warn"
        return "good"

    return ""


def normalize_reading(reading: RawTelemetry) -> VitalSign:
    """Convert a single RawTelemetry into a VitalSign with status."""
    spec = THRESHOLD_MAP.get(reading.metric)

    if spec is None:
        # Unknown metric -- pass through with no status
        return VitalSign(
            label=reading.metric.upper().replace("_", " "),
            value=f"{reading.value} {reading.unit}",
            raw_value=reading.value,
            unit=reading.unit,
            status="",
        )

    # Format display value
    direction = spec["direction"]
    fmt = spec.get("fmt", "{}")

    if direction == "bool_bad":
        display = "ACTIVE" if reading.value >= 1.0 else "OK"
    elif reading.metric == "compressor_running":
        display = "RUNNING" if reading.value >= 1.0 else "STOPPED"
    else:
        try:
            display = f"{fmt.format(reading.value)} {reading.unit}"
        except (ValueError, KeyError):
            display = f"{reading.value} {reading.unit}"

    status = evaluate_status(
        value=reading.value,
        direction=direction,
        warn=spec.get("warn"),
        crit=spec.get("crit"),
    )

    return VitalSign(
        label=spec["label"],
        value=display,
        raw_value=reading.value,
        unit=reading.unit,
        status=status,
    )


def normalize_batch(readings: list[RawTelemetry]) -> list[VitalSign]:
    """Normalize a batch of raw readings into VitalSigns."""
    vitals = []
    for r in readings:
        try:
            vitals.append(normalize_reading(r))
        except Exception as e:
            logger.warning("normalize_failed", metric=r.metric, error=str(e))
    return vitals
