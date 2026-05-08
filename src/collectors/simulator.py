"""
Aevus Testbed — Telemetry Simulator
Generates realistic fake telemetry for all lab devices.
Full wellsite profile: compressor, well, separator, tanks, safety, power.

Usage:
    collector = SimulatorCollector("RTU-01", device_type="rtu")
    readings = await collector.poll()
"""

import math
import random

from src.collectors.base import BaseCollector
from src.models.telemetry import RawTelemetry

# ── Radio Profile ───────────────────────────────────────────────
RADIO_PROFILES = {
    "rssi":          {"base": -68.0, "drift": 5.0, "unit": "dBm",   "noise": 2.0,  "group": "rf"},
    "snr":           {"base": 22.0,  "drift": 3.0, "unit": "dB",    "noise": 1.5,  "group": "rf"},
    "tx_power":      {"base": 30.0,  "drift": 1.0, "unit": "dBm",   "noise": 0.5,  "group": "rf"},
    "rx_packets":    {"base": 50000, "drift": 5000,"unit": "count",  "noise": 1000, "group": "traffic"},
    "tx_packets":    {"base": 48000, "drift": 5000,"unit": "count",  "noise": 1000, "group": "traffic"},
    "error_packets": {"base": 12,    "drift": 8,   "unit": "count",  "noise": 5,    "group": "traffic"},
    "temperature":   {"base": 42.0,  "drift": 8.0, "unit": "°C",    "noise": 1.0,  "group": "environment"},
    "voltage":       {"base": 13.8,  "drift": 0.3, "unit": "V",     "noise": 0.1,  "group": "power"},
}

# ── RTU / Wellsite Profile ──────────────────────────────────────
RTU_PROFILES = {
    # Compressor
    "suction_pressure":     {"base": 450.0,  "drift": 50.0,  "unit": "PSI",   "noise": 10.0, "group": "compressor"},
    "discharge_pressure":   {"base": 1050.0, "drift": 80.0,  "unit": "PSI",   "noise": 15.0, "group": "compressor"},
    "gas_temperature":      {"base": 145.0,  "drift": 15.0,  "unit": "°F",    "noise": 3.0,  "group": "compressor"},
    "vibration":            {"base": 2.8,    "drift": 1.5,   "unit": "mm/s",  "noise": 0.5,  "group": "compressor"},
    "motor_current":        {"base": 85.0,   "drift": 12.0,  "unit": "A",     "noise": 3.0,  "group": "compressor"},
    "compressor_rpm":       {"base": 1200.0, "drift": 100.0, "unit": "RPM",   "noise": 15.0, "group": "compressor"},
    "interstage_temp":      {"base": 195.0,  "drift": 20.0,  "unit": "°F",    "noise": 4.0,  "group": "compressor"},
    "oil_pressure":         {"base": 55.0,   "drift": 8.0,   "unit": "PSI",   "noise": 2.0,  "group": "compressor"},
    "coolant_temp":         {"base": 175.0,  "drift": 15.0,  "unit": "°F",    "noise": 3.0,  "group": "compressor"},
    "run_hours":            {"base": 12450,  "drift": 0,     "unit": "hrs",   "noise": 0,    "group": "compressor"},
    "compressor_running":   {"base": 1.0,    "drift": 0,     "unit": "bool",  "noise": 0,    "group": "compressor"},
    "compressor_loaded":    {"base": 1.0,    "drift": 0,     "unit": "bool",  "noise": 0,    "group": "compressor"},
    "high_pressure_alarm":  {"base": 0.0,    "drift": 0,     "unit": "bool",  "noise": 0,    "group": "compressor"},
    "high_temp_alarm":      {"base": 0.0,    "drift": 0,     "unit": "bool",  "noise": 0,    "group": "compressor"},
    "low_oil_pressure":     {"base": 0.0,    "drift": 0,     "unit": "bool",  "noise": 0,    "group": "compressor"},

    # Well
    "casing_pressure":      {"base": 320.0,  "drift": 30.0,  "unit": "PSI",   "noise": 5.0,  "group": "well"},
    "tubing_pressure":      {"base": 280.0,  "drift": 25.0,  "unit": "PSI",   "noise": 5.0,  "group": "well"},
    "flow_rate":            {"base": 2.8,    "drift": 0.5,   "unit": "MCFD",  "noise": 0.2,  "group": "well"},
    "oil_production_rate":  {"base": 45.0,   "drift": 8.0,   "unit": "BOPD",  "noise": 3.0,  "group": "well"},
    "water_cut":            {"base": 22.0,   "drift": 5.0,   "unit": "%",     "noise": 2.0,  "group": "well"},
    "choke_position":       {"base": 65.0,   "drift": 10.0,  "unit": "%",     "noise": 1.0,  "group": "well"},

    # Separator / Tanks / Production
    "separator_pressure":   {"base": 125.0,  "drift": 15.0,  "unit": "PSI",   "noise": 3.0,  "group": "production"},
    "separator_level":      {"base": 55.0,   "drift": 10.0,  "unit": "%",     "noise": 2.0,  "group": "production"},
    "separator_diff_press": {"base": 4.5,    "drift": 1.5,   "unit": "PSI",   "noise": 0.5,  "group": "production"},
    "oil_tank_level":       {"base": 72.0,   "drift": 15.0,  "unit": "in",    "noise": 2.0,  "group": "production"},
    "water_tank_level":     {"base": 48.0,   "drift": 12.0,  "unit": "in",    "noise": 2.0,  "group": "production"},
    "lact_meter_rate":      {"base": 8.5,    "drift": 2.0,   "unit": "BBL/h", "noise": 0.5,  "group": "production"},
    "flare_active":         {"base": 1.0,    "drift": 0,     "unit": "bool",  "noise": 0,    "group": "production"},
    "tank_high_level":      {"base": 0.0,    "drift": 0,     "unit": "bool",  "noise": 0,    "group": "production"},

    # Power
    "battery_voltage":      {"base": 13.2,   "drift": 0.5,   "unit": "VDC",   "noise": 0.1,  "group": "power"},
    "solar_voltage":        {"base": 18.5,   "drift": 3.0,   "unit": "VDC",   "noise": 0.5,  "group": "power"},
    "low_battery_alarm":    {"base": 0.0,    "drift": 0,     "unit": "bool",  "noise": 0,    "group": "power"},

    # Environment
    "ambient_temperature":  {"base": 88.0,   "drift": 12.0,  "unit": "°F",    "noise": 2.0,  "group": "environment"},

    # Safety
    "h2s_level":            {"base": 1.2,    "drift": 0.8,   "unit": "PPM",   "noise": 0.3,  "group": "safety"},
    "lel_level":            {"base": 3.0,    "drift": 2.0,   "unit": "%LEL",  "noise": 0.5,  "group": "safety"},
    "esd_activated":        {"base": 0.0,    "drift": 0,     "unit": "bool",  "noise": 0,    "group": "safety"},
    "h2s_alarm":            {"base": 0.0,    "drift": 0,     "unit": "bool",  "noise": 0,    "group": "safety"},
    "lel_alarm":            {"base": 0.0,    "drift": 0,     "unit": "bool",  "noise": 0,    "group": "safety"},
    "communication_fault":  {"base": 0.0,    "drift": 0,     "unit": "bool",  "noise": 0,    "group": "system"},
}

# ── Network Device Profile ──────────────────────────────────────
ROUTER_PROFILES = {
    "cpu_load":       {"base": 15.0,  "drift": 10.0, "unit": "%",   "noise": 3.0, "group": "system"},
    "memory_usage":   {"base": 45.0,  "drift": 10.0, "unit": "%",   "noise": 2.0, "group": "system"},
    "uptime":         {"base": 720.0, "drift": 0,    "unit": "hrs", "noise": 0,   "group": "system"},
}

DEVICE_PROFILES = {
    "radio": RADIO_PROFILES,
    "rtu": RTU_PROFILES,
    "router": ROUTER_PROFILES,
    "switch": ROUTER_PROFILES,
}


class SimulatorCollector(BaseCollector):
    """Generates simulated telemetry for testing without hardware."""

    def __init__(
        self,
        asset_id: str,
        device_type: str = "radio",
        poll_interval: int = 5,
        degradation: float = 0.0,
    ):
        super().__init__(asset_id, host="simulator", poll_interval=poll_interval)
        self.device_type = device_type
        self.degradation = degradation
        self.profiles = DEVICE_PROFILES.get(device_type, RADIO_PROFILES)
        self._tick = 0

    async def is_reachable(self) -> bool:
        """Simulator is always reachable."""
        return True

    async def poll(self) -> list[RawTelemetry]:
        """Generate simulated readings with realistic drift and noise."""
        self._tick += 1
        readings: list[RawTelemetry] = []

        for metric, profile in self.profiles.items():
            value = self._simulate_value(profile)
            readings.append(
                self._make_reading(
                    metric=metric,
                    value=round(value, 3),
                    unit=profile["unit"],
                    source="simulator",
                    group=profile.get("group", ""),
                )
            )

        return readings

    def _simulate_value(self, profile: dict) -> float:
        """Generate a realistic value with sinusoidal drift, noise, and degradation."""
        base = profile["base"]
        drift = profile["drift"]
        noise = profile["noise"]

        if drift == 0 and noise == 0:
            if profile["unit"] == "bool":
                return base
            if profile["unit"] == "hrs":
                return base + (self._tick * self.poll_interval / 3600.0)
            return base

        # Sinusoidal drift (simulates day/night, load cycles)
        time_factor = math.sin(self._tick * 0.05) * drift

        # Random noise
        noise_factor = random.gauss(0, noise)

        # Degradation shifts values toward thresholds
        degradation_shift = 0.0
        if self.degradation > 0:
            degradation_shift = -abs(drift) * self.degradation * 2 if base < 0 else abs(drift) * self.degradation * 1.5

        return base + time_factor + noise_factor + degradation_shift
