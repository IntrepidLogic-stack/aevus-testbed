"""
Aevus Testbed — Telemetry Simulator
Generates realistic fake telemetry for all lab devices.
Use this for local development and testing without hardware.

Usage:
    collector = SimulatorCollector("RAD-01", device_type="radio")
    readings = await collector.poll()
"""

import math
import random

from src.collectors.base import BaseCollector
from src.models.telemetry import RawTelemetry

# Realistic value ranges per device type
RADIO_PROFILES = {
    "rssi": {"base": -68.0, "drift": 5.0, "unit": "dBm", "noise": 2.0},
    "snr": {"base": 22.0, "drift": 3.0, "unit": "dB", "noise": 1.5},
    "tx_power": {"base": 30.0, "drift": 1.0, "unit": "dBm", "noise": 0.5},
    "rx_packets": {"base": 50000, "drift": 5000, "unit": "count", "noise": 1000},
    "tx_packets": {"base": 48000, "drift": 5000, "unit": "count", "noise": 1000},
    "error_packets": {"base": 12, "drift": 8, "unit": "count", "noise": 5},
    "temperature": {"base": 42.0, "drift": 8.0, "unit": "°C", "noise": 1.0},
    "voltage": {"base": 13.8, "drift": 0.3, "unit": "V", "noise": 0.1},
}

RTU_PROFILES = {
    "suction_pressure": {"base": 450.0, "drift": 50.0, "unit": "PSI", "noise": 10.0},
    "discharge_pressure": {"base": 1050.0, "drift": 80.0, "unit": "PSI", "noise": 15.0},
    "flow_rate": {"base": 2.8, "drift": 0.5, "unit": "MCFD", "noise": 0.2},
    "gas_temperature": {"base": 145.0, "drift": 15.0, "unit": "°F", "noise": 3.0},
    "ambient_temperature": {"base": 88.0, "drift": 12.0, "unit": "°F", "noise": 2.0},
    "battery_voltage": {"base": 13.2, "drift": 0.5, "unit": "VDC", "noise": 0.1},
    "solar_voltage": {"base": 18.5, "drift": 3.0, "unit": "VDC", "noise": 0.5},
    "tank_level": {"base": 36.0, "drift": 12.0, "unit": "in", "noise": 1.0},
    "vibration": {"base": 2.8, "drift": 1.5, "unit": "mm/s", "noise": 0.5},
    "run_hours": {"base": 12450, "drift": 0, "unit": "hrs", "noise": 0},
    "compressor_running": {"base": 1.0, "drift": 0, "unit": "bool", "noise": 0},
    "high_pressure_alarm": {"base": 0.0, "drift": 0, "unit": "bool", "noise": 0},
    "low_battery_alarm": {"base": 0.0, "drift": 0, "unit": "bool", "noise": 0},
    "communication_fault": {"base": 0.0, "drift": 0, "unit": "bool", "noise": 0},
}

ROUTER_PROFILES = {
    "cpu_load": {"base": 15.0, "drift": 10.0, "unit": "%", "noise": 3.0},
    "memory_usage": {"base": 45.0, "drift": 10.0, "unit": "%", "noise": 2.0},
    "uptime": {"base": 720.0, "drift": 0, "unit": "hrs", "noise": 0},
}

DEVICE_PROFILES = {
    "radio": RADIO_PROFILES,
    "rtu": RTU_PROFILES,
    "router": ROUTER_PROFILES,
    "switch": ROUTER_PROFILES,  # same metrics for now
}


class SimulatorCollector(BaseCollector):
    """Generates simulated telemetry for testing without hardware."""

    # expected_metrics is populated per-instance in __init__ based on the
    # configured device_type, since one class serves radio / rtu / router
    # simulations with different metric sets.

    def __init__(
        self,
        asset_id: str,
        device_type: str = "radio",
        poll_interval: int = 5,
        degradation: float = 0.0,
    ):
        super().__init__(asset_id, host="simulator", poll_interval=poll_interval)
        self.device_type = device_type
        self.degradation = degradation  # 0.0 = healthy, 1.0 = failing
        self.profiles = DEVICE_PROFILES.get(device_type, RADIO_PROFILES)
        # Shadow the class attribute with a per-instance frozenset matching
        # the configured device profile.
        self.expected_metrics = frozenset(self.profiles.keys())
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
                )
            )

        return readings

    def _simulate_value(self, profile: dict) -> float:
        """Generate a realistic value with sinusoidal drift, noise, and degradation."""
        base = profile["base"]
        drift = profile["drift"]
        noise = profile["noise"]

        if drift == 0 and noise == 0:
            # Static values (run_hours, booleans)
            if profile["unit"] == "bool":
                return base  # Could add random flips for alarm simulation
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
            # For negative-is-bad metrics (RSSI), push more negative
            if base < 0:
                degradation_shift = -abs(drift) * self.degradation * 2
            else:
                degradation_shift = abs(drift) * self.degradation * 1.5

        return base + time_factor + noise_factor + degradation_shift
