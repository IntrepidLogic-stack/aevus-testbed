"""
Aevus Testbed — Asset Data Model
Represents any monitored device in the lab fleet.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from src.models.telemetry import VitalSign


class AssetEvent(BaseModel):
    """A timestamped event on an asset (status change, alert, etc.)."""

    timestamp: datetime
    severity: Literal["good", "warn", "bad", "info"]
    message: str


class Asset(BaseModel):
    """A monitored asset in the Aevus fleet."""

    id: str  # "RAD-01", "RTU-01", "SW-01", "RTR-01"
    type: Literal["radio", "rtu", "switch", "router", "sensor"]
    status: Literal["good", "warn", "bad", "unknown", "offline"] = "unknown"
    name: str  # "Trio JR900 #1"
    location: str  # "Lab Cabinet"
    health: int | None = None  # 0-100, None if unknown
    last_seen: datetime | None = None
    vendor: str
    model: str
    firmware: str | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    protocol: str = "snmp"  # "snmp", "modbus", "dnp3"
    poll_interval: int = 30  # seconds
    latitude: float | None = None
    longitude: float | None = None
    vitals: list[VitalSign] = []
    events: list[AssetEvent] = []
