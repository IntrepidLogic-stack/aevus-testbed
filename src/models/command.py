"""
Aevus — Command Data Models
"""

from __future__ import annotations

from datetime import datetime  # runtime: Pydantic field type, needed for OpenAPI schema (#210)

from pydantic import BaseModel


class CommandRequest(BaseModel):
    """Operator command request."""

    asset_id: str
    command: str
    params: dict = {}
    confirm: bool = False
    operator: str = "api"


class CommandLogEntry(BaseModel):
    """Audit log entry for an executed command."""

    id: int | None = None
    asset_id: str
    command: str
    params: str = "{}"
    operator: str = "api"
    timestamp: datetime | None = None
    result: str = ""
    il9000_check: str = "pass"
