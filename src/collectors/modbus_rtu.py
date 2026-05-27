"""
Aevus Testbed — SCADAPack 470 Modbus TCP Collector
Polls Schneider SCADAPack 470 RTU via Modbus TCP on port 502.

Register map per Aevus Live Testbed Setup Guide:
  40001-40019: Holding registers (analog process values)
  10001-10004: Discrete inputs (alarm states)
"""

import struct

from pymodbus.client import AsyncModbusTcpClient

from src.collectors.base import BaseCollector
from src.models.telemetry import RawTelemetry

# SCADAPack 470 Modbus Holding Register Map
# Each Float32 spans 2 consecutive 16-bit registers
HOLDING_REGISTERS = {
    "suction_pressure": {"address": 40001, "type": "float32", "unit": "PSI"},
    "discharge_pressure": {"address": 40003, "type": "float32", "unit": "PSI"},
    "flow_rate": {"address": 40005, "type": "float32", "unit": "MCFD"},
    "gas_temperature": {"address": 40007, "type": "float32", "unit": "°F"},
    "ambient_temperature": {"address": 40009, "type": "float32", "unit": "°F"},
    "battery_voltage": {"address": 40011, "type": "float32", "unit": "VDC"},
    "solar_voltage": {"address": 40013, "type": "float32", "unit": "VDC"},
    "tank_level": {"address": 40015, "type": "float32", "unit": "in"},
    "vibration": {"address": 40017, "type": "float32", "unit": "mm/s"},
    "run_hours": {"address": 40019, "type": "uint32", "unit": "hrs"},
}

# SCADAPack 470 Discrete Input Map
DISCRETE_INPUTS = {
    "compressor_running": {"address": 10001, "description": "Compressor run status"},
    "high_pressure_alarm": {"address": 10002, "description": "High pressure shutdown"},
    "low_battery_alarm": {"address": 10003, "description": "Battery below threshold"},
    "communication_fault": {"address": 10004, "description": "Comm link status"},
}


class SCADAPack470Collector(BaseCollector):
    """Collects telemetry from a SCADAPack 470 RTU via Modbus TCP."""

    # All holding registers and discrete inputs must respond on a healthy
    # RTU. A missing process value (e.g. suction_pressure absent while
    # battery_voltage still reports) indicates a sensor or channel fault.
    expected_metrics = frozenset(HOLDING_REGISTERS.keys()) | frozenset(DISCRETE_INPUTS.keys())

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
            # Try reading one register to verify communication
            result = await client.read_holding_registers(
                address=0,  # 40001 in Modbus protocol = offset 0
                count=2,
                slave=self.slave_id,
            )
            return not result.isError()
        except Exception:
            return False

    async def poll(self) -> list[RawTelemetry]:
        """Poll all SCADAPack 470 registers and return raw telemetry."""
        readings: list[RawTelemetry] = []
        client = await self._get_client()

        # Read all holding registers in one batch (40001-40020 = offset 0, count 20)
        result = await client.read_holding_registers(
            address=0,
            count=20,
            slave=self.slave_id,
        )
        if result.isError():
            self.log.error("modbus_read_failed", error=str(result))
            return []

        regs = result.registers

        # Decode each metric from the register block
        for metric, spec in HOLDING_REGISTERS.items():
            offset = spec["address"] - 40001  # Convert to 0-based offset
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
                    )
                )
            except (IndexError, struct.error) as e:
                self.log.warning("register_decode_failed", metric=metric, error=str(e))

        # Read discrete inputs (10001-10004 = offset 0, count 4)
        disc_result = await client.read_discrete_inputs(
            address=0,
            count=4,
            slave=self.slave_id,
        )
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
