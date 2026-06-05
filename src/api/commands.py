"""
Aevus — Operator Commands API Router
"""

from __future__ import annotations

from fastapi import APIRouter

from src.models.command import CommandRequest  # runtime: request-body type, needed for OpenAPI schema (#210)

router = APIRouter(tags=["commands"])


@router.post("/commands")
async def execute_command(request: CommandRequest):
    """Execute an operator command with safety checks."""
    from src.main import app_state

    entry = app_state.commander.execute(request)
    return entry.model_dump(mode="json")


@router.get("/commands/log")
async def get_command_log(limit: int = 100):
    """Retrieve the command audit trail."""
    from src.main import app_state

    entries = app_state.commander.get_log(limit=limit)
    return [e.model_dump(mode="json") for e in entries]
