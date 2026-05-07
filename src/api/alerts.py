"""
Aevus Testbed --- Alert API Routes
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.models.alert import Alert

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[Alert])
async def list_alerts(
    severity: str | None = Query(None, description="Filter by severity"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000),
) -> list[Alert]:
    """List alerts with optional severity/status filters."""
    from src.main import app_state

    return app_state.db.list_alerts(severity=severity, status=status, limit=limit)


@router.post("/{alert_id}/acknowledge", response_model=Alert)
async def acknowledge_alert(alert_id: str) -> Alert:
    """Acknowledge an open alert."""
    from src.main import app_state

    alert = app_state.alert_engine.acknowledge(alert_id, db=app_state.db)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found or already acknowledged")

    app_state.db.save_alert(alert)
    return alert
