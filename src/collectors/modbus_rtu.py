"""
Aevus Testbed — SCADAPack 470 Modbus TCP Collector
Polls Schneider SCADAPack 470 RTU via Modbus TCP on port 502.

Register map per Aevus Live Testbed Setup Guide:
  40001-40049: Holding registers (analog process values)
  10001-10012: Discrete inputs (alarm/status states)

Full wellsite profile: compressor, well, separator, tanks, safety.
"""

import struct

from pymodbus.client import AsyncModbusTcpClient

from src.collectors.base import BaseCollector
from src.models.telemetry import RawTelemetry

# ── SCADAPack 470 Holding Register Map ──────────────────────────
# Each Float32 spans 2 consecutive 16-bit registers.
# uint32 also spans 2 registers.
HOLDING_REGISTERS = {
    # --- Compressor ---
    "suction_pressure":     {"address": 40001, "type": "float32", "unit": "PSI",  "group": "compressor"},
    "discharge_pressure":   {"address": 40003, "type": "float32", "unit": "PSI",  "group": "compressor"},
    "gas_temperature":      {"address": 40005, "type": "float32", "unit": "°F",   "group": "compressor"},
    "vibration":            {"address": 40007, "type": "float32", "unit": "mm/s", "group": "compressor"},
    "motor_current":        {"address": 40009, "type": "float32", "unit": "A",    "group": "compressor"},
    "compressor_rpm":       {"address": 40011, "type": "float32", "unit": "RPM",  "group": "compressor"},
    "interstage_temp":      {"address": 40013, "type": "float32", "unit": "°F",   "group": "compressor"},
    "oil_pressure":         {"address": 40015, "type": "float32", "unit": "PSI",  "group": "compressor"},
    "coolant_temp":         {"address": 40017, "type": "float32", "unit": "°F",   "group": "compressor"},
    "run_hours":            {"address": 40019, "type": "uint32",  "unit": "hrs",  "group": "compressor"},

    # --- Well ---
    "casing_pressure":      {"address": 40021, "type": "float32", "unit": "PSI",  "group": "well"},
    "tubing_pressure":      {"address": 40023, "type": "float32", "unit": "PSI",  "group": "well"},
    "flow_rate":            {"address": 40025, "type": "float32", "unit": "MCFD", "group": "well"},
    "oil_production_rate":  {"address": 40027, "type": "float32", "unit": "BOPD", "group": "well"},
    "water_cut":            {"address": 40029, "type": "float32", "unit": "%",    "group": "well"},
    "choke_position":       {"address": 40031, "type": "float32", "unit": "%",    "group": "well"},

    # --- Separator / Tanks ---
    "separator_pressure":   {"address": 40033, "type": "float32", "unit": "PSI",  "group": "production"},
    "separator_level":      {"address": 40035, "type": "float32", "unit": "%",    "group": "production"},
    "separator_diff_press": {"address": 40037, "type": "float32", "unit": "PSI",  "group": "production"},
    "oil_tank_level":       {"address": 40039, "type": "float32", "unit": "in",   "group": "production"},
    "water_tank_level":     {"address": 40041, "type": "float32", "unit": "in",   "group": "production"},
    "lact_meter_rate":      {"address": 40043, "type": "float32", "unit": "BBL/h","group": "production"},

    # --- Power & Environment ---
    "battery_voltage":      {"address": 40045, "type": "float32", "unit": "VDC",  "group": "power"},
    "solar_voltage":        {"address": 40047, "type": "float32", "unit": "VDC",  "group": "power"},
    "ambient_temperature":  {"address": 40049, "type": "float32", "unit": "°F",   "group": "environment"},
    "h2s_level":            {"address": 40051, "type": "float32", "unit": "PPM",  "group": "safety"},
    "lel_level":            {"address": 40053, "type": "float32", "unit": "%LEL", "group": "safety"},
}

# ── SCADAPack 470 Discrete Input Map ────────────────────────────
DISCRETE_INPUTS = {
    "compressor_running":    {"address": 10001, "description": "Compressor run status",       "group": "compressor"},
    "compressor_loaded":     {"address": 10002, "description": "Compressor load status",      "group": "compressor"},
    "high_pressure_alarm":   {"address": 10003, "description": "High pressure shutdown",      "group": "compressor"},
    "high_temp_alarm":       {"address": 10004, "description": "High temperature shutdown",   "group": "compressor"},
    "low_oil_pressure":      {"address": 10005, "description": "Low lube oil pressure",       "group": "compressor"},
    "low_battery_alarm":     {"address": 10006, "description": "Battery below threshold",     "group": "power"},
    "communication_fault":   {"address": 10007, "description": "Comm link status",            "group": "system"},
    "esd_activated":         {"address": 10008, "description": "Emergency shutdown active",   "group": "safety"},
    "h2s_alarm":             {"address": 10009, "description": "H2S high alarm",              "group": "safety"},
    "lel_alarm":             {"address": 10010, "description": "LEL high alarm",              "group": "safety"},
    "flare_active":          {"address": 10011, "description": "Flare pilot status",          "group": "production"},
    "tank_high_level":       {"address": 10012, "description": "Oil tank high level alarm",   "group": "production"},
}


class SCADAPack470Collector(BaseCollector):
    """Collects telemetry from a SCADAPack 470 RTU via Modbus TCP."""

    def __init__(
        self,
        asset_id: str,
        host: str,
        port: int = 502,
        slave_id: int = 1,
        poll_interval: int = 5,
    ):
        super().__init__(asset_id, host, poll_interval)
        self.port = port
        self.slave_id = slave_id
        self._client: AsyncModbusTcpClient | None = None

    async def _get_client(self) -> AsyncModbusTcpClient:
        """Get or create the Modbus TCP client connection."""
        if self._client is None or not self._client.connected:
            self._client = AsyncModbusTcpClient(
                host=self.host,
                port=self.port,
                timeout=5,
            )
            connected = await self._client.connect()
            if not connected:
                raise ConnectionError(f"Cannot connect to Modbus TCP at {self.host}:{self.port}")
        return self._client

    async def is_reachable(self) -> bool:
        """Check if the RTU responds to a Modbus connection."""
        try:
            client = await self._get_client()
            result = await client.read_holding_registers(address=0, count=2)
            return not result.isError()
        except Exception:
            return False

    async def poll(self) -> list[RawTelemetry]:
        """Poll all SCADAPack 470 registers and return raw telemetry."""
        readings: list[RawTelemetry] = []
        client = await self._get_client()

        # Read all holding registers in one batch (40001-40054 = offset 0, count 54)
        result = await client.read_holding_registers(address=0, count=54)
        if result.isError():
            self.log.error("modbus_read_failed", error=str(result))
            return []

        regs = result.registers

        # Decode each metric from the register block
        for metric, spec in HOLDING_REGISTERS.items():
            offset = spec["address"] - 40001
            try:
                if spec["type"] == "float32":
                    value = self._decode_float32(regs[offset], regs[offset + 1])
                elif spec["type"] == "uint32":
                    value = float((regs[offset] << 16) | regs[offset + 1])
                else:
                    continue

                readings.append(
                    self._make_reading(
                        metric=metric,
                        value=value,
                        unit=spec["unit"],
                        source="modbus",
                        modbus_register=spec["address"],
                        group=spec["group"],
                    )
                )
            except (IndexError, struct.error) as e:
                self.log.warning("register_decode_failed", metric=metric, error=str(e))

        # Read discrete inputs (10001-10012 = offset 0, count 12)
        disc_result = await client.read_discrete_inputs(address=0, count=12)
        if not disc_result.isError():
            for i, (metric, spec) in enumerate(DISCRETE_INPUTS.items()):
                try:
                    value = float(disc_result.bits[i])
                    readings.append(
                        self._make_reading(
                            metric=metric,
                            value=value,
                            unit="bool",
                            source="modbus",
                            modbus_register=spec["address"],
                            group=spec["group"],
                        )
                    )
                except (IndexError, TypeError):
                    pass

        return readings

    async def close(self) -> None:
        """Close the Modbus TCP connection."""
        if self._client and self._client.connected:
            self._client.close()
            self._client = None

    @staticmethod
    def _decode_float32(reg_hi: int, reg_lo: int) -> float:
        """Decode two 16-bit registers into a 32-bit float (big-endian)."""
        raw_bytes = struct.pack(">HH", reg_hi, reg_lo)
        return struct.unpack(">f", raw_bytes)[0]
