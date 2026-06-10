"""
Aevus Testbed — Telemetry Data Models
Raw telemetry readings from collectors before normalization.
"""

from datetime import datetime

from pydantic import BaseModel


class VitalSign(BaseModel):
    """A single vital-sign reading for an asset."""

    label: str  # e.g. "RSSI", "SUCTION PRESSURE"
    value: str  # e.g. "-68 dBm", "245.3 PSI"
    raw_value: float  # numeric for computation
    unit: str  # "dBm", "PSI", "MCFD", "%"
    status: str = ""  # "good", "warn", "bad", or ""
    group: str = ""  # compressor, well, production, safety, power, etc.
    source: str = ""  # "snmp", "modbus", "dnp3", "simulator"


class RawTelemetry(BaseModel):
    """A single raw telemetry reading from a collector."""

    asset_id: str
    metric: str  # e.g. "rssi", "suction_pressure", "if_in_octets"
    value: float
    unit: str
    timestamp: datetime
    source: str  # "snmp", "modbus", "dnp3", "simulator", "opcua"
    oid: str | None = None  # SNMP OID if applicable
    modbus_register: int | None = None  # Modbus register if applicable
    opcua_node: str | None = None  # OPC UA NodeId string if applicable (e.g. "ns=3;s=Sinusoid")
    group: str = ""  # Logical group: compressor, well, production, safety, power, etc.
