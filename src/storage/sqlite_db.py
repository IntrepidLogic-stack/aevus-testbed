"""
Aevus Testbed --- SQLite Storage Layer
Asset registry, alert log, and configuration persistence.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import structlog

from src.config import settings
from src.models.alert import Alert
from src.models.asset import Asset, AssetEvent
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
    events_json TEXT NOT NULL DEFAULT '[]',
    latitude REAL,
    longitude REAL
);


CREATE TABLE IF NOT EXISTS asset_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    note TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT 'System',
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    entry TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT 'System',
    category TEXT NOT NULL DEFAULT 'general',
    created_at TEXT NOT NULL
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

-- ISA-18.2 tracker baselines (survive service restart)
CREATE TABLE IF NOT EXISTS firmware_baselines (
    asset_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runhours_baselines (
    asset_id TEXT PRIMARY KEY,
    run_hours INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

-- Per-poll reachability samples for rolling uptime % (24h window).
-- One row per asset per poll; ok=1 when the collector reached the device.
-- Pruned to ~25h on write so the table stays small.
CREATE TABLE IF NOT EXISTS reachability_samples (
    asset_id TEXT NOT NULL,
    ts INTEGER NOT NULL,  -- epoch seconds
    ok INTEGER NOT NULL   -- 1 = reachable, 0 = poll failed
);
CREATE INDEX IF NOT EXISTS idx_reach_asset_ts
    ON reachability_samples (asset_id, ts);

-- ISA-18.2 §11 operator shelving audit log
CREATE TABLE IF NOT EXISTS shelve_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    metric_label TEXT NOT NULL,
    action TEXT NOT NULL,  -- 'shelve' | 'unshelve' | 'expire'
    duration_s INTEGER,
    expires_at TEXT,
    reason TEXT,
    operator TEXT NOT NULL DEFAULT 'system',
    created_at TEXT NOT NULL
);
"""


class SQLiteDB:
    """SQLite storage for asset registry and alert log."""

    def __init__(self, db_path: str | None = None) -> None:
        self._path = db_path or settings.sqlite_path
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self.log = logger.bind(component="sqlite")
        self._connect()

    def _connect(self) -> None:
        """Open (or reopen) the database connection."""
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        try:
            self._conn.execute('ALTER TABLE assets ADD COLUMN latitude REAL')
        except Exception:
            pass
        try:
            self._conn.execute('ALTER TABLE assets ADD COLUMN longitude REAL')
        except Exception:
            pass

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
               protocol, poll_interval, vitals_json, events_json, latitude, longitude)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               status=excluded.status, health=excluded.health,
               last_seen=excluded.last_seen, vitals_json=excluded.vitals_json,
               events_json=excluded.events_json, firmware=excluded.firmware,
               ip_address=excluded.ip_address,
               latitude=excluded.latitude, longitude=excluded.longitude""",
            (
                asset.id,
                asset.type,
                asset.status,
                asset.name,
                asset.location,
                asset.health,
                asset.last_seen.isoformat() if asset.last_seen else None,
                asset.vendor,
                asset.model,
                asset.firmware,
                asset.ip_address,
                asset.mac_address,
                asset.protocol,
                asset.poll_interval,
                json.dumps([v.model_dump() for v in asset.vitals]),
                json.dumps([e.model_dump(mode="json") for e in asset.events]),
                asset.latitude,
                asset.longitude,
            ),
        )
        self._conn.commit()

    def get_asset(self, asset_id: str) -> Asset | None:
        """Fetch a single asset by ID."""
        row = self._conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_asset(row)

    def list_assets(
        self,
        type_filter: str | None = None,
        status_filter: str | None = None,
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
                alert.id,
                alert.severity,
                alert.asset_id,
                alert.asset_name,
                alert.message,
                alert.risk_score,
                alert.detected_at.isoformat(),
                alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
                alert.resolved_at.isoformat() if alert.resolved_at else None,
                alert.status,
            ),
        )
        self._conn.commit()

    def list_alerts(
        self,
        severity: str | None = None,
        status: str | None = None,
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

    def get_alert(self, alert_id: str) -> Alert | None:
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
            latitude=row.get("latitude", None),
            longitude=row.get("longitude", None),
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


    # ── Notes CRUD ──

    def add_note(self, asset_id: str, note: str, author: str = "System") -> int:
        """Add a note to an asset. Returns the note ID."""
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            "INSERT INTO asset_notes (asset_id, note, author, created_at) VALUES (?, ?, ?, ?)",
            (asset_id, note, author, now),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_note(self, note_id: int, note: str) -> bool:
        """Update an existing note."""
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            "UPDATE asset_notes SET note = ?, updated_at = ? WHERE id = ?",
            (note, now, note_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def delete_note(self, note_id: int) -> bool:
        """Delete a note."""
        cur = self._conn.execute("DELETE FROM asset_notes WHERE id = ?", (note_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def list_notes(self, asset_id: str) -> list[dict]:
        """List all notes for an asset."""
        rows = self._conn.execute(
            "SELECT * FROM asset_notes WHERE asset_id = ? ORDER BY created_at DESC",
            (asset_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Journal CRUD ──

    def add_journal_entry(self, asset_id: str, entry: str, author: str = "System", category: str = "general") -> int:
        """Add an immutable journal entry. Returns the entry ID."""
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            "INSERT INTO journal (asset_id, entry, author, category, created_at) VALUES (?, ?, ?, ?, ?)",
            (asset_id, entry, author, category, now),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_journal(self, asset_id: str | None = None, category: str | None = None, limit: int = 100) -> list[dict]:
        """List journal entries with optional filters."""
        query = "SELECT * FROM journal WHERE 1=1"
        params: list = []
        if asset_id:
            query += " AND asset_id = ?"
            params.append(asset_id)
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ---- ISA-18.2 tracker persistence ----------------------------------
    # Implements the Protocols expected by FirmwareTracker / MaintenanceTracker.

    def get_firmware_version(self, asset_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT version FROM firmware_baselines WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        return row["version"] if row else None

    def set_firmware_version(self, asset_id: str, version: str) -> None:
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO firmware_baselines (asset_id, version, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(asset_id) DO UPDATE SET
                 version=excluded.version,
                 updated_at=excluded.updated_at""",
            (asset_id, version, now),
        )
        self._conn.commit()

    def get_runhours_baseline(self, asset_id: str) -> int | None:
        row = self._conn.execute(
            "SELECT run_hours FROM runhours_baselines WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        return row["run_hours"] if row else None

    def set_runhours_baseline(self, asset_id: str, run_hours: int) -> None:
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO runhours_baselines (asset_id, run_hours, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(asset_id) DO UPDATE SET
                 run_hours=excluded.run_hours,
                 updated_at=excluded.updated_at""",
            (asset_id, run_hours, now),
        )
        self._conn.commit()

    # ---- Reachability / rolling uptime % -------------------------------

    def record_reachability(self, asset_id: str, ok: bool) -> None:
        """Record one poll outcome and prune samples older than ~25h."""
        import time
        now = int(time.time())
        self._conn.execute(
            "INSERT INTO reachability_samples (asset_id, ts, ok) VALUES (?, ?, ?)",
            (asset_id, now, 1 if ok else 0),
        )
        # Keep the window bounded (25h) so the table never grows unbounded.
        self._conn.execute(
            "DELETE FROM reachability_samples WHERE asset_id = ? AND ts < ?",
            (asset_id, now - 90000),
        )
        self._conn.commit()

    def uptime_pct(self, asset_id: str, window_seconds: int = 86400) -> float | None:
        """Rolling uptime % over the window. None if no samples yet.

        Uptime = successful polls / total polls in the window. Returns a
        float 0-100 rounded to 1 decimal. None when there's no data so the
        caller can show "—" rather than a fake 100%.
        """
        import time
        cutoff = int(time.time()) - window_seconds
        row = self._conn.execute(
            """SELECT COUNT(*) AS total, COALESCE(SUM(ok), 0) AS up
                 FROM reachability_samples
                WHERE asset_id = ? AND ts >= ?""",
            (asset_id, cutoff),
        ).fetchone()
        total = row["total"] if row else 0
        if not total:
            return None
        return round((row["up"] / total) * 100.0, 1)

    # ---- Shelve audit log (ISA-18.2 §11.4) -----------------------------

    def log_shelve_action(
        self,
        asset_id: str,
        metric_label: str,
        action: str,
        duration_s: int | None = None,
        expires_at: str | None = None,
        reason: str | None = None,
        operator: str = "system",
    ) -> int:
        """Append an audit row for shelve/unshelve/expire events."""
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            """INSERT INTO shelve_audit
                 (asset_id, metric_label, action, duration_s, expires_at, reason, operator, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (asset_id, metric_label, action, duration_s, expires_at, reason, operator, now),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_shelve_audit(self, asset_id: str | None = None, limit: int = 100) -> list[dict]:
        query = "SELECT * FROM shelve_audit WHERE 1=1"
        params: list = []
        if asset_id:
            query += " AND asset_id = ?"
            params.append(asset_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
