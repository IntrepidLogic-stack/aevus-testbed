"""
Aevus Testbed --- WebSocket Manager
Manages connected dashboard clients and pushes real-time updates.
"""

from __future__ import annotations

import json
import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Any

logger = structlog.get_logger()
router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections for real-time push."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self.log = logger.bind(component="ws")

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        self.log.info("ws_connected", total=len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        self.log.info("ws_disconnected", total=len(self._connections))

    async def broadcast(self, event_type: str, data: Any) -> None:
        """Broadcast a JSON message to all connected clients."""
        if not self._connections:
            return
        message = json.dumps({"type": event_type, "data": data}, default=str)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def client_count(self) -> int:
        return len(self._connections)


# Singleton — imported by scheduler to push updates
ws_manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket endpoint for real-time dashboard updates."""
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
