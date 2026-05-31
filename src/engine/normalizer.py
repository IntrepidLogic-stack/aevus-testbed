"""
Aevus Testbed --- Telemetry Normalizer
Converts raw collector readings into VitalSign objects with status tagging.

Each metric has thresholds that determine good/warn/bad status.
The normalizer is the bridge between raw numeric telemetry and the
human-readable vitals shown on the dashboard.
"""

from __future__ import annotations

from typing import Literal

import structlog

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
        "warn": settings.threshold_rssi_warn,  # -80
        "crit": settings.threshold_rssi_crit,  # -90
        "label": "RSSI",
        "fmt": "{:.0f}",
    },
    "snr": {
        "direction": "lower_bad",
        "warn": settings.threshold_snr_warn,  # 15
        "crit": settings.threshold_snr_crit,  # 10
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
        "warn": settings.threshold_suction_warn,  # 800
        "crit": settings.threshold_suction_crit,  # 900
        "label": "SUCTION PRESSURE",
        "fmt": "{:.1f}",
    },
    "discharge_pressure": {
        "direction": "upper_bad",
        "warn": settings.threshold_discharge_warn,  # 1200
        "crit": settings.threshold_discharge_crit,  # 1400
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
        "warn": settings.threshold_battery_warn,  # 12.0
        "crit": settings.threshold_battery_crit,  # 11.5
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
        "warn": settings.threshold_vibration_warn,  # 4.5
        "crit": settings.threshold_vibration_crit,  # 7.1
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
    # --- RTU expanded: compressor ---
    "motor_current": {
        "direction": "upper_bad",
        "warn": 110.0,
        "crit": 130.0,
        "label": "MOTOR CURRENT",
        "fmt": "{:.1f}",
    },
    "compressor_rpm": {
        "direction": "info",
        "label": "COMPRESSOR RPM",
        "fmt": "{:,.0f}",
    },
    "interstage_temp": {
        "direction": "upper_bad",
        "warn": 250.0,
        "crit": 300.0,
        "label": "INTERSTAGE TEMP",
        "fmt": "{:.1f}",
    },
    "oil_pressure": {
        "direction": "lower_bad",
        "warn": 35.0,
        "crit": 25.0,
        "label": "OIL PRESSURE",
        "fmt": "{:.1f}",
    },
    "coolant_temp": {
        "direction": "upper_bad",
        "warn": 210.0,
        "crit": 230.0,
        "label": "COOLANT TEMP",
        "fmt": "{:.1f}",
    },
    "compressor_loaded": {
        "direction": "info",
        "label": "COMPRESSOR LOADED",
        "fmt": "{}",
    },
    "high_temp_alarm": {
        "direction": "bool_bad",
        "label": "HIGH TEMP ALARM",
        "fmt": "{}",
    },
    "low_oil_pressure": {
        "direction": "bool_bad",
        "label": "LOW OIL PRESSURE",
        "fmt": "{}",
    },
    # --- RTU expanded: well ---
    "casing_pressure": {
        "direction": "upper_bad",
        "warn": 400.0,
        "crit": 500.0,
        "label": "CASING PRESSURE",
        "fmt": "{:.1f}",
    },
    "tubing_pressure": {
        "direction": "upper_bad",
        "warn": 350.0,
        "crit": 450.0,
        "label": "TUBING PRESSURE",
        "fmt": "{:.1f}",
    },
    "oil_production_rate": {
        "direction": "info",
        "label": "OIL PRODUCTION",
        "fmt": "{:.1f}",
    },
    "water_cut": {
        "direction": "upper_bad",
        "warn": 40.0,
        "crit": 60.0,
        "label": "WATER CUT",
        "fmt": "{:.1f}",
    },
    "choke_position": {
        "direction": "info",
        "label": "CHOKE POSITION",
        "fmt": "{:.0f}",
    },
    # --- RTU expanded: production ---
    "separator_pressure": {
        "direction": "upper_bad",
        "warn": 175.0,
        "crit": 200.0,
        "label": "SEPARATOR PRESS",
        "fmt": "{:.1f}",
    },
    "separator_level": {
        "direction": "upper_bad",
        "warn": 80.0,
        "crit": 90.0,
        "label": "SEPARATOR LEVEL",
        "fmt": "{:.0f}",
    },
    "separator_diff_press": {
        "direction": "upper_bad",
        "warn": 8.0,
        "crit": 12.0,
        "label": "SEPARATOR DIFF",
        "fmt": "{:.1f}",
    },
    "oil_tank_level": {
        "direction": "upper_bad",
        "warn": 110.0,
        "crit": 130.0,
        "label": "OIL TANK LEVEL",
        "fmt": "{:.1f}",
    },
    "water_tank_level": {
        "direction": "upper_bad",
        "warn": 90.0,
        "crit": 110.0,
        "label": "WATER TANK LEVEL",
        "fmt": "{:.1f}",
    },
    "lact_meter_rate": {
        "direction": "info",
        "label": "LACT METER",
        "fmt": "{:.1f}",
    },
    "flare_active": {
        "direction": "info",
        "label": "FLARE STATUS",
        "fmt": "{}",
    },
    "tank_high_level": {
        "direction": "bool_bad",
        "label": "TANK HIGH LEVEL",
        "fmt": "{}",
    },
    # --- RTU expanded: safety ---
    "h2s_level": {
        "direction": "upper_bad",
        "warn": 5.0,
        "crit": 10.0,
        "label": "H2S",
        "fmt": "{:.1f}",
    },
    "lel_level": {
        "direction": "upper_bad",
        "warn": 10.0,
        "crit": 20.0,
        "label": "LEL",
        "fmt": "{:.1f}",
    },
    "esd_activated": {
        "direction": "bool_bad",
        "label": "ESD STATUS",
        "fmt": "{}",
    },
    "h2s_alarm": {
        "direction": "bool_bad",
        "label": "H2S ALARM",
        "fmt": "{}",
    },
    "lel_alarm": {
        "direction": "bool_bad",
        "label": "LEL ALARM",
        "fmt": "{}",
    },
    # --- Network (MikroTik / Catalyst) ---
    "cpu_load": {
        "direction": "upper_bad",
        "warn": settings.threshold_cpu_warn,  # 70
        "crit": settings.threshold_cpu_crit,  # 90
        "label": "CPU LOAD",
        "fmt": "{:.0f}",
    },
    "memory_usage": {
        "direction": "upper_bad",
        "warn": 80.0,
        "crit": 95.0,
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
        "warn": settings.threshold_if_errors_warn,  # 100
        "crit": settings.threshold_if_errors_crit,  # 1000
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
    # --- Edge (Raspberry Pi) ---
    "disk_used": {
        "direction": "upper_bad",
        "warn": 80.0,
        "crit": 95.0,
        "label": "DISK USAGE",
        "fmt": "{:.0f}",
    },
    "cpu_temp": {
        "direction": "upper_bad",
        "warn": 70.0,
        "crit": 80.0,
        "label": "CPU TEMP",
        "fmt": "{:.1f}",
    },
    "memory_used": {
        "direction": "upper_bad",
        "warn": 80.0,
        "crit": 95.0,
        "label": "MEMORY USED",
        "fmt": "{:.0f}",
    },
    "process_count": {
        "direction": "info",
        "label": "PROCESSES",
        "fmt": "{:.0f}",
    },
    "uptime_hours": {
        "direction": "info",
        "label": "UPTIME",
        "fmt": "{:,.0f}",
    },
    "load_avg_1m": {
        "direction": "upper_bad",
        "warn": 2.0,
        "crit": 4.0,
        "label": "LOAD AVG 1M",
        "fmt": "{:.2f}",
    },
    "load_avg_5m": {
        "direction": "upper_bad",
        "warn": 2.0,
        "crit": 4.0,
        "label": "LOAD AVG 5M",
        "fmt": "{:.2f}",
    },
    "uptime": {
        "direction": "info",
        "label": "UPTIME",
        "fmt": "{:,.1f}",
    },
    # --- Radio (Trio JR900) missing entries ---
    "signal_quality": {
        "direction": "lower_bad",
        "warn": 50.0,
        "crit": 25.0,
        "label": "SIGNAL QUALITY",
        "fmt": "{:.0f}",
    },
    "link_state": {
        # bool_good (not bool_bad): for radios, value=1 means LINKED which
        # is the HEALTHY state. The generic bool_bad path would mislabel
        # ACTIVE radios as "bad" (caught by data-coverage audit 2026-05-30).
        "direction": "bool_good",
        "label": "LINK STATE",
        "fmt": "{}",
    },
    "tx_error": {
        "direction": "info",
        "label": "TX ERRORS",
        "fmt": "{:,.0f}",
    },
    "rx_error": {
        "direction": "info",
        "label": "RX ERRORS",
        "fmt": "{:,.0f}",
    },
    "rx_dropped": {
        "direction": "info",
        "label": "RX DROPPED",
        "fmt": "{:,.0f}",
    },
    "latency": {
        # ICMP round-trip heartbeat to the radio. Local P2P links are a few ms;
        # rising latency is an early warning of congestion / marginal RF.
        "direction": "upper_bad",
        "warn": 50.0,
        "crit": 200.0,
        "label": "LATENCY",
        "fmt": "{:.0f}",
    },
    "radio_role": {
        "direction": "info",
        "label": "ROLE",
        "fmt": "{}",
    },
    # --- Switch (Cisco) ---
    "cpu_load_1min": {
        "direction": "upper_bad",
        "warn": 70.0,
        "crit": 90.0,
        "label": "CPU LOAD 1MIN",
        "fmt": "{:.0f}",
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
        # 1.0 = alarm active = bad (high_pressure_alarm, comm_fault, etc.)
        return "bad" if value >= 1.0 else "good"
    if direction == "bool_good":
        # 1.0 = healthy state = good (link_state when LINKED, etc.)
        return "good" if value >= 1.0 else "bad"
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
        # Check for interface oper_status metrics (dynamic per-interface)
        if reading.metric.endswith("_oper_status"):
            is_up = reading.value == 1.0
            iface_label = reading.metric.replace("_oper_status", "").replace("_", " ").strip('"').upper()
            return VitalSign(
                label=iface_label,
                value="UP" if is_up else "DOWN",
                raw_value=reading.value,
                unit="",
                status="good" if is_up else "bad",
                group=reading.group or "traffic",
                source=reading.source,
            )

        return VitalSign(
            label=reading.metric.upper().replace("_", " "),
            value=f"{reading.value} {reading.unit}",
            raw_value=reading.value,
            unit=reading.unit,
            status="",
            group=reading.group,
            source=reading.source,
        )

    # Format display value
    direction = spec["direction"]
    fmt = spec.get("fmt", "{}")

    # Metric-specific display strings — checked BEFORE generic direction
    # branches so a metric with bool_good/bool_bad direction can still
    # use its own friendly label (e.g. link_state → LINKED, not ACTIVE).
    if reading.metric == "compressor_running":
        display = "RUNNING" if reading.value >= 1.0 else "STOPPED"
    elif reading.metric == "compressor_loaded":
        display = "LOADED" if reading.value >= 1.0 else "UNLOADED"
    elif reading.metric == "flare_active":
        display = "LIT" if reading.value >= 1.0 else "OUT"
    elif reading.metric == "link_state":
        display = "LINKED" if reading.value >= 1.0 else "DOWN"
    elif direction == "bool_bad":
        display = "ACTIVE" if reading.value >= 1.0 else "OK"
    elif direction == "bool_good":
        display = "OK" if reading.value >= 1.0 else "DOWN"
    elif reading.metric == "radio_role":
        # Trio JR900: 1 = Access Point (master), 2 = Remote (slave)
        display = "MASTER" if reading.value == 1.0 else "SLAVE" if reading.value == 2.0 else "—"
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
        group=reading.group,
        source=reading.source,
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
