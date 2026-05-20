"""
Aevus Testbed --- SQLite Storage Layer
Asset registry, alert log, and configuration persistence.
"""

from __future__ import annotations

import json
import sqlite3
import structlog
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.config import settings
from src.models.asset import Asset, AssetEvent
from src.models.alert import Alert
from src.models.telemetry import VitalSign

logger = structlog.get_logger()

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    name TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT 'Lab Cabinet',
    health INTEGER,
    last_seen TEXT,
    vendor TEXT NOT NULL,
    model TEXT NOT NULL,
    firmware TEXT,
    ip_address TEXT,
    mac_address TEXT,
    protocol TEXT NOT NULL DEFAULT 'snmp',
    poll_interval INTEGER NOT NULL DEFAULT 30,
    vitals_json TEXT NOT NULL DEFAULT '[]',
    events_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    severity TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    asset_name TEXT NOT NULL,
    message TEXT NOT NULL,
    risk_score INTEGER,
    detected_at TEXT NOT NULL,
    acknowledged_at TEXT,
    resolved_at TEXT,
    status TEXT NOT NULL DEFAULT 'open'
);
"""


class SQLiteDB:
    """SQLite storage for asset registry and alert log."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._path = db_path or settings.sqlite_path
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self.log = logger.bind(component="sqlite")
        self._connect()

    def _connect(self) -> None:
        """Open (or reopen) the database connection."""
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def reconnect(self) -> None:
        """Reconnect if the connection was closed."""
        try:
            self._conn.execute("SELECT 1")
        except (sqlite3.ProgrammingError, AttributeError):
            self._connect()

    # ── Asset CRUD ──

    def upsert_asset(self, asset: Asset) -> None:
        """Insert or update an asset in the registry."""
        self._conn.execute(
            """INSERT INTO assets (id, type, status, name, location, health,
               last_seen, vendor, model, firmware, ip_address, mac_address,
               protocol, poll_interval, vitals_json, events_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               status=excluded.status, health=excluded.health,
               last_seen=excluded.last_seen, vitals_json=excluded.vitals_json,
               events_json=excluded.events_json, firmware=excluded.firmware,
               ip_address=excluded.ip_address""",
            (
                asset.id, asset.type, asset.status, asset.name, asset.location,
                asset.health,
                asset.last_seen.isoformat() if asset.last_seen else None,
                asset.vendor, asset.model, asset.firmware,
                asset.ip_address, asset.mac_address, asset.protocol,
                asset.poll_interval,
                json.dumps([v.model_dump() for v in asset.vitals]),
                json.dumps([e.model_dump(mode="json") for e in asset.events]),
            ),
        )
        self._conn.commit()

    def get_asset(self, asset_id: str) -> Optional[Asset]:
        """Fetch a single asset by ID."""
        row = self._conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_asset(row)

    def get_asset_by_ip(self, ip_address: str) -> Optional[Asset]:
        """Resolve an asset by its registered IP address.

        Used by the SNMP trap receiver to map trap source IPs to asset
        IDs. Returns None when no asset matches — the caller should log
        and drop unknown sources.
        """
        row = self._conn.execute(
            "SELECT * FROM assets WHERE ip_address = ? LIMIT 1",
            (ip_address,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_asset(row)

    def list_assets(
        self,
        type_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> list[Asset]:
        """List all assets with optional filters."""
        query = "SELECT * FROM assets WHERE 1=1"
        params: list = []
        if type_filter:
            query += " AND type = ?"
            params.append(type_filter)
        if status_filter:
            query += " AND status = ?"
            params.append(status_filter)
        query += " ORDER BY id"

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_asset(r) for r in rows]

    # ── Alert CRUD ──

    def save_alert(self, alert: Alert) -> None:
        """Insert or update an alert."""
        self._conn.execute(
            """INSERT INTO alerts (id, severity, asset_id, asset_name, message,
               risk_score, detected_at, acknowledged_at, resolved_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               severity=excluded.severity, message=excluded.message,
               acknowledged_at=excluded.acknowledged_at,
               resolved_at=excluded.resolved_at, status=excluded.status""",
            (
                alert.id, alert.severity, alert.asset_id, alert.asset_name,
                alert.message, alert.risk_score,
                alert.detected_at.isoformat(),
                alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
                alert.resolved_at.isoformat() if alert.resolved_at else None,
                alert.status,
            ),
        )
        self._conn.commit()

    def list_alerts(
        self,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[Alert]:
        """List alerts with optional filters."""
        query = "SELECT * FROM alerts WHERE 1=1"
        params: list = []
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_alert(r) for r in rows]

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        """Fetch a single alert by ID."""
        row = self._conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_alert(row)

    # ── Helpers ──

    @staticmethod
    def _row_to_asset(row: sqlite3.Row) -> Asset:
        vitals = [VitalSign(**v) for v in json.loads(row["vitals_json"])]
        events = [AssetEvent(**e) for e in json.loads(row["events_json"])]
        return Asset(
            id=row["id"],
            type=row["type"],
            status=row["status"],
            name=row["name"],
            location=row["location"],
            health=row["health"],
            last_seen=datetime.fromisoformat(row["last_seen"]) if row["last_seen"] else None,
            vendor=row["vendor"],
            model=row["model"],
            firmware=row["firmware"],
            ip_address=row["ip_address"],
            mac_address=row["mac_address"],
            protocol=row["protocol"],
            poll_interval=row["poll_interval"],
            vitals=vitals,
            events=events,
        )

    @staticmethod
    def _row_to_alert(row: sqlite3.Row) -> Alert:
        return Alert(
            id=row["id"],
            severity=row["severity"],
            asset_id=row["asset_id"],
            asset_name=row["asset_name"],
            message=row["message"],
            risk_score=row["risk_score"],
            detected_at=datetime.fromisoformat(row["detected_at"]),
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]) if row["acknowledged_at"] else None,
            resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
            status=row["status"],
        )

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
