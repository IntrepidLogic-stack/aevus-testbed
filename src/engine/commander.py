"""
Aevus — Operator Command Interface
Handles operator commands with IL-9000 safety checks and audit logging.
Commands are simulated (logged but Modbus writes go to simulator).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import structlog

from src.config import settings
from src.il9000 import IL_9000_ENFORCED
from src.models.command import CommandLogEntry, CommandRequest

logger = structlog.get_logger()

# Supported commands and their Modbus mappings
COMMAND_MAP: dict[str, dict] = {
    "start_motor": {"type": "coil", "address": 0, "value": True, "fc": 5},
    "stop_motor": {"type": "coil", "address": 0, "value": False, "fc": 5},
    "open_valve": {"type": "coil", "address": 1, "value": True, "fc": 5},
    "close_valve": {"type": "coil", "address": 1, "value": False, "fc": 5},
    "set_setpoint": {"type": "register", "address": 100, "fc": 6},
}

COMMAND_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS command_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    command TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    operator TEXT NOT NULL DEFAULT 'api',
    timestamp TEXT NOT NULL,
    result TEXT NOT NULL,
    il9000_check TEXT NOT NULL DEFAULT 'pass'
);
"""


class Commander:
    """Operator command processor with safety interlocks and audit trail."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.sqlite_path
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Commander keeps its own connection to the shared sqlite file (for the
        # command_log table). WAL + busy_timeout let it coexist with SQLiteDB's
        # connection without "database is locked" under write contention. (M4)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(COMMAND_LOG_SCHEMA)
        self.log = logger.bind(component="commander")

    def execute(self, request: CommandRequest) -> CommandLogEntry:
        """Execute an operator command with safety checks.

        All commands are simulated — no actual Modbus writes to live PLCs.
        """
        now = datetime.now(UTC)

        # Validate command
        if request.command not in COMMAND_MAP:
            entry = self._log_command(request, now, result="rejected: unknown command", il9000="n/a")
            self.log.warning("command_rejected", reason="unknown_command", command=request.command)
            return entry

        # Require explicit confirmation
        if not request.confirm:
            entry = self._log_command(request, now, result="rejected: confirmation required", il9000="n/a")
            self.log.warning("command_rejected", reason="no_confirmation", command=request.command)
            return entry

        # IL-9000 safety interlock check
        # For operator commands (not firmware), we check that IL-9000 is enforced
        # (meaning the safety system is active). Commands proceed only when safety is on.
        il9000_status = "pass" if IL_9000_ENFORCED else "FAIL_SAFETY_DISABLED"
        if not IL_9000_ENFORCED:
            entry = self._log_command(
                request, now, result="rejected: IL-9000 safety system offline", il9000=il9000_status
            )
            self.log.error("command_rejected_safety", command=request.command)
            return entry

        # Execute (simulated)
        cmd_def = COMMAND_MAP[request.command]
        result = f"simulated: {request.command} on {request.asset_id} (FC{cmd_def['fc']} addr={cmd_def['address']})"

        entry = self._log_command(request, now, result=result, il9000=il9000_status)
        self.log.warning(
            "command_executed",
            asset_id=request.asset_id,
            command=request.command,
            operator=request.operator,
            result=result,
        )
        return entry

    def get_log(self, limit: int = 100) -> list[CommandLogEntry]:
        """Retrieve the command audit trail."""
        rows = self._conn.execute("SELECT * FROM command_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [
            CommandLogEntry(
                id=r["id"],
                asset_id=r["asset_id"],
                command=r["command"],
                params=r["params"],
                operator=r["operator"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
                result=r["result"],
                il9000_check=r["il9000_check"],
            )
            for r in rows
        ]

    def _log_command(
        self,
        request: CommandRequest,
        timestamp: datetime,
        result: str,
        il9000: str,
    ) -> CommandLogEntry:
        """Write a command to the audit log and return the entry."""
        params_json = json.dumps(request.params)
        self._conn.execute(
            """INSERT INTO command_log
               (asset_id, command, params, operator, timestamp, result, il9000_check)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                request.asset_id,
                request.command,
                params_json,
                request.operator,
                timestamp.isoformat(),
                result,
                il9000,
            ),
        )
        self._conn.commit()

        row = self._conn.execute("SELECT last_insert_rowid() as id").fetchone()

        return CommandLogEntry(
            id=row["id"],
            asset_id=request.asset_id,
            command=request.command,
            params=params_json,
            operator=request.operator,
            timestamp=timestamp,
            result=result,
            il9000_check=il9000,
        )
