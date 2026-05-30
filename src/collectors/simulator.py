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
    "rssi": {"base": -68.0, "drift": 5.0, "unit": "dBm", "noise": 2.0, "group": "rf"},
    "snr": {"base": 22.0, "drift": 3.0, "unit": "dB", "noise": 1.5, "group": "rf"},
    "tx_power": {"base": 30.0, "drift": 1.0, "unit": "dBm", "noise": 0.5, "group": "rf"},
    "rx_packets": {"base": 50000, "drift": 5000, "unit": "count", "noise": 1000, "group": "traffic"},
    "tx_packets": {"base": 48000, "drift": 5000, "unit": "count", "noise": 1000, "group": "traffic"},
    "error_packets": {"base": 12, "drift": 8, "unit": "count", "noise": 5, "group": "traffic"},
    "temperature": {"base": 42.0, "drift": 8.0, "unit": "°C", "noise": 1.0, "group": "environment"},
    "voltage": {"base": 13.8, "drift": 0.3, "unit": "V", "noise": 0.1, "group": "power"},
}

# ── RTU / Wellsite Profile (Permian Basin / Gulf Coast midstream) ──
RTU_PROFILES = {
    # Compressor (low-pressure gathering)
    "suction_pressure": {"base": 28.0, "drift": 8.0, "unit": "PSI", "noise": 2.0, "group": "compressor"},
    "discharge_pressure": {"base": 89.0, "drift": 12.0, "unit": "PSI", "noise": 3.0, "group": "compressor"},
    "gas_temperature": {"base": 140.0, "drift": 15.0, "unit": "°F", "noise": 3.0, "group": "compressor"},
    "vibration": {"base": 2.8, "drift": 1.5, "unit": "mm/s", "noise": 0.5, "group": "compressor"},
    "motor_current": {"base": 85.0, "drift": 12.0, "unit": "A", "noise": 3.0, "group": "compressor"},
    "compressor_rpm": {"base": 1180.0, "drift": 100.0, "unit": "RPM", "noise": 15.0, "group": "compressor"},
    "interstage_temp": {"base": 195.0, "drift": 20.0, "unit": "°F", "noise": 4.0, "group": "compressor"},
    "oil_pressure": {"base": 55.0, "drift": 8.0, "unit": "PSI", "noise": 2.0, "group": "compressor"},
    "coolant_temp": {"base": 175.0, "drift": 15.0, "unit": "°F", "noise": 3.0, "group": "compressor"},
    "run_hours": {"base": 12450, "drift": 0, "unit": "hrs", "noise": 0, "group": "compressor"},
    "compressor_running": {"base": 1.0, "drift": 0, "unit": "bool", "noise": 0, "group": "compressor"},
    "compressor_loaded": {"base": 1.0, "drift": 0, "unit": "bool", "noise": 0, "group": "compressor"},
    "high_pressure_alarm": {"base": 0.0, "drift": 0, "unit": "bool", "noise": 0, "group": "compressor"},
    "high_temp_alarm": {"base": 0.0, "drift": 0, "unit": "bool", "noise": 0, "group": "compressor"},
    "low_oil_pressure": {"base": 0.0, "drift": 0, "unit": "bool", "noise": 0, "group": "compressor"},
    # Well
    "casing_pressure": {"base": 325.0, "drift": 30.0, "unit": "PSI", "noise": 5.0, "group": "well"},
    "tubing_pressure": {"base": 285.0, "drift": 25.0, "unit": "PSI", "noise": 5.0, "group": "well"},
    "flow_rate": {"base": 3.2, "drift": 0.5, "unit": "MCFD", "noise": 0.2, "group": "well"},
    "oil_production_rate": {"base": 45.0, "drift": 8.0, "unit": "BOPD", "noise": 3.0, "group": "well"},
    "water_cut": {"base": 36.0, "drift": 5.0, "unit": "%", "noise": 2.0, "group": "well"},
    "choke_position": {"base": 65.0, "drift": 10.0, "unit": "%", "noise": 1.0, "group": "well"},
    # Separator / Tanks / Production
    "separator_pressure": {"base": 125.0, "drift": 15.0, "unit": "PSI", "noise": 3.0, "group": "production"},
    "separator_level": {"base": 55.0, "drift": 10.0, "unit": "%", "noise": 2.0, "group": "production"},
    "separator_diff_press": {"base": 4.5, "drift": 1.5, "unit": "PSI", "noise": 0.5, "group": "production"},
    "oil_tank_level": {"base": 72.0, "drift": 15.0, "unit": "in", "noise": 2.0, "group": "production"},
    "water_tank_level": {"base": 48.0, "drift": 12.0, "unit": "in", "noise": 2.0, "group": "production"},
    "lact_meter_rate": {"base": 8.5, "drift": 2.0, "unit": "BBL/h", "noise": 0.5, "group": "production"},
    "flare_active": {"base": 1.0, "drift": 0, "unit": "bool", "noise": 0, "group": "production"},
    "tank_high_level": {"base": 0.0, "drift": 0, "unit": "bool", "noise": 0, "group": "production"},
    # Power
    "battery_voltage": {"base": 13.4, "drift": 0.5, "unit": "VDC", "noise": 0.1, "group": "power"},
    "solar_voltage": {"base": 14.8, "drift": 3.0, "unit": "VDC", "noise": 0.5, "group": "power"},
    "charge_current": {"base": 2.2, "drift": 0.5, "unit": "A", "noise": 0.1, "group": "power"},
    "low_battery_alarm": {"base": 0.0, "drift": 0, "unit": "bool", "noise": 0, "group": "power"},
    # Environment
    "ambient_temperature": {"base": 92.0, "drift": 12.0, "unit": "°F", "noise": 2.0, "group": "environment"},
    "enclosure_temp": {"base": 98.0, "drift": 8.0, "unit": "°F", "noise": 1.5, "group": "environment"},
    # Safety
    "h2s_level": {"base": 1.2, "drift": 0.8, "unit": "PPM", "noise": 0.3, "group": "safety"},
    "lel_level": {"base": 3.0, "drift": 2.0, "unit": "%LEL", "noise": 0.5, "group": "safety"},
    "esd_activated": {"base": 0.0, "drift": 0, "unit": "bool", "noise": 0, "group": "safety"},
    "h2s_alarm": {"base": 0.0, "drift": 0, "unit": "bool", "noise": 0, "group": "safety"},
    "lel_alarm": {"base": 0.0, "drift": 0, "unit": "bool", "noise": 0, "group": "safety"},
    "communication_fault": {"base": 0.0, "drift": 0, "unit": "bool", "noise": 0, "group": "system"},
}

# ── EFM Profile (TotalFlow XFC G4 meter station) ───────────────
EFM_PROFILES = {
    "differential_pressure": {"base": 53.7, "drift": 8.0, "unit": "inH2O", "noise": 1.5, "group": "production"},
    "static_pressure": {"base": 497.0, "drift": 15.0, "unit": "PSIG", "noise": 3.0, "group": "production"},
    "flow_temperature": {"base": 77.6, "drift": 3.0, "unit": "°F", "noise": 0.5, "group": "production"},
    "flow_rate": {"base": 3.9, "drift": 0.8, "unit": "MCFD", "noise": 0.2, "group": "production"},
    "accumulated_volume": {"base": 125944.0, "drift": 0, "unit": "MCF", "noise": 0, "group": "production"},
    "energy_rate": {"base": 3.8, "drift": 0.5, "unit": "MMBTU/D", "noise": 0.1, "group": "production"},
    "btu_content": {"base": 1034.6, "drift": 5.0, "unit": "BTU/CF", "noise": 1.0, "group": "production"},
    "specific_gravity": {"base": 0.62, "drift": 0.02, "unit": "SG", "noise": 0.005, "group": "production"},
    "co2_content": {"base": 0.9, "drift": 0.15, "unit": "%", "noise": 0.03, "group": "production"},
    "h2s_content": {"base": 0.5, "drift": 0.2, "unit": "PPM", "noise": 0.05, "group": "production"},
    "upstream_pressure": {"base": 538.0, "drift": 10.0, "unit": "PSIG", "noise": 2.0, "group": "production"},
    "downstream_pressure": {"base": 500.0, "drift": 12.0, "unit": "PSIG", "noise": 2.5, "group": "production"},
    "valve_position": {"base": 75.9, "drift": 5.0, "unit": "%", "noise": 1.0, "group": "production"},
    "battery_voltage": {"base": 13.5, "drift": 0.4, "unit": "VDC", "noise": 0.1, "group": "power"},
    "solar_voltage": {"base": 14.5, "drift": 2.5, "unit": "VDC", "noise": 0.5, "group": "power"},
    "line_pressure": {"base": 510.0, "drift": 15.0, "unit": "PSIG", "noise": 3.0, "group": "production"},
    "line_temperature": {"base": 82.0, "drift": 5.0, "unit": "°F", "noise": 1.0, "group": "production"},
}

# ── Edge Profile (Raspberry Pi edge collector) ──────────────────
EDGE_PROFILES = {
    "cpu_load": {"base": 12.0, "drift": 8.0, "unit": "%", "noise": 2.0, "group": "system"},
    "memory_used": {"base": 42.0, "drift": 10.0, "unit": "%", "noise": 2.0, "group": "system"},
    "disk_used": {"base": 28.0, "drift": 2.0, "unit": "%", "noise": 0.5, "group": "system"},
    "cpu_temp": {"base": 52.0, "drift": 8.0, "unit": "°C", "noise": 1.5, "group": "environment"},
    "uptime_hours": {"base": 2160.0, "drift": 0, "unit": "hrs", "noise": 0, "group": "system"},
    "process_count": {"base": 145.0, "drift": 20.0, "unit": "count", "noise": 5.0, "group": "system"},
}

# ── Switch Profile (Cisco Catalyst 2960) ────────────────────────
SWITCH_PROFILES = {
    "cpu_load": {"base": 8.0, "drift": 5.0, "unit": "%", "noise": 1.5, "group": "system"},
    "memory_used": {"base": 35.0, "drift": 8.0, "unit": "%", "noise": 2.0, "group": "system"},
    "port_1_in_octets": {"base": 850000.0, "drift": 200000.0, "unit": "bytes", "noise": 50000, "group": "traffic"},
    "port_1_out_octets": {"base": 720000.0, "drift": 180000.0, "unit": "bytes", "noise": 40000, "group": "traffic"},
    "port_1_status": {"base": 1.0, "drift": 0, "unit": "bool", "noise": 0, "group": "traffic"},
    "port_errors": {"base": 2.0, "drift": 3.0, "unit": "count", "noise": 1.0, "group": "traffic"},
    "temperature": {"base": 38.0, "drift": 5.0, "unit": "°C", "noise": 1.0, "group": "environment"},
    "poe_power": {"base": 12.5, "drift": 3.0, "unit": "W", "noise": 0.5, "group": "power"},
    "uptime_hours": {"base": 4320.0, "drift": 0, "unit": "hrs", "noise": 0, "group": "system"},
}

# ── Router Profile (MikroTik L009) ──────────────────────────────
ROUTER_PROFILES = {
    "cpu_load": {"base": 15.0, "drift": 10.0, "unit": "%", "noise": 3.0, "group": "system"},
    "memory_used": {"base": 48.0, "drift": 12.0, "unit": "%", "noise": 2.0, "group": "system"},
    "wan_in_octets": {"base": 1200000.0, "drift": 400000.0, "unit": "bytes", "noise": 80000, "group": "traffic"},
    "wan_out_octets": {"base": 950000.0, "drift": 300000.0, "unit": "bytes", "noise": 60000, "group": "traffic"},
    "active_connections": {"base": 24.0, "drift": 8.0, "unit": "count", "noise": 2.0, "group": "traffic"},
    "temperature": {"base": 45.0, "drift": 6.0, "unit": "°C", "noise": 1.0, "group": "environment"},
    "voltage": {"base": 24.1, "drift": 0.3, "unit": "VDC", "noise": 0.05, "group": "power"},
    "uptime_hours": {"base": 3600.0, "drift": 0, "unit": "hrs", "noise": 0, "group": "system"},
}

DEVICE_PROFILES = {
    "radio": RADIO_PROFILES,
    "rtu": RTU_PROFILES,
    "router": ROUTER_PROFILES,
    "switch": SWITCH_PROFILES,
    "efm": EFM_PROFILES,
    "edge": EDGE_PROFILES,
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
        # Monotonically increasing state trackers
        self._accumulated_volume = self.profiles.get("accumulated_volume", {}).get("base", 0.0)
        self._uptime_hours = self.profiles.get("uptime_hours", {}).get("base", 0.0)
        self._run_hours = self.profiles.get("run_hours", {}).get("base", 0.0)

    async def is_reachable(self) -> bool:
        """Simulator is always reachable."""
        return True

    async def poll(self) -> list[RawTelemetry]:
        """Generate simulated readings with realistic drift and noise."""
        self._tick += 1
        readings: list[RawTelemetry] = []

        for metric, profile in self.profiles.items():
            value = self._simulate_value(metric, profile)
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

    def _simulate_value(self, metric: str, profile: dict) -> float:
        """Generate a realistic value with sinusoidal drift, noise, and degradation."""
        base = profile["base"]
        drift = profile["drift"]
        noise = profile["noise"]

        # Monotonically increasing metrics
        if metric == "accumulated_volume":
            self._accumulated_volume += random.uniform(0.001, 0.005)
            return self._accumulated_volume
        if metric == "uptime_hours":
            self._uptime_hours += self.poll_interval / 3600.0
            return self._uptime_hours
        if metric == "run_hours":
            self._run_hours += self.poll_interval / 3600.0
            return self._run_hours

        if drift == 0 and noise == 0:
            if profile["unit"] == "bool":
                return base
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
