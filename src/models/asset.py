"""
Aevus Testbed — Asset Data Model
Represents any monitored device in the lab fleet.
"""

from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Literal

from src.models.telemetry import VitalSign


class AssetEvent(BaseModel):
    """A timestamped event on an asset (status change, alert, etc.)."""

    timestamp: datetime
    severity: Literal["good", "warn", "bad", "info"]
    message: str


class Asset(BaseModel):
    """A monitored asset in the Aevus fleet."""

    id: str                     # "RAD-01", "RTU-01", "SW-01", "RTR-01"
    type: Literal["radio", "rtu", "switch", "router", "sensor"]
    status: Literal["good", "warn", "bad", "unknown", "offline"] = "unknown"
    name: str                   # "Trio JR900 #1"
    location: str               # "Lab Cabinet"
    health: Optional[int] = None  # 0-100, None if unknown
    last_seen: Optional[datetime] = None
    vendor: str
    model: str
    firmware: Optional[str] = None
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    protocol: str = "snmp"      # "snmp", "modbus", "dnp3"
    poll_interval: int = 30     # seconds
    vitals: list[VitalSign] = []
    events: list[AssetEvent] = []
