"""
Aevus Testbed --- Reports API Routes
Generate on-demand compliance and operational reports.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/fleet-health")
async def fleet_health_report(
    hours: int = Query(24, ge=1, le=720),
) -> dict:
    """Generate a fleet health summary report."""
    from src.main import app_state

    assets = app_state.db.list_assets()
    now = datetime.now(UTC)

    asset_rows = []
    for a in assets:
        asset_rows.append({
            "id": a.id,
            "name": a.name,
            "type": a.type,
            "status": a.status,
            "health": a.health,
            "last_seen": a.last_seen.isoformat() if a.last_seen else None,
        })

    scores = [a.health for a in assets if a.health is not None]
    return {
        "report": "fleet-health",
        "generated_at": now.isoformat(),
        "period_hours": hours,
        "total_assets": len(assets),
        "avg_health": round(sum(scores) / len(scores)) if scores else None,
        "assets": asset_rows,
        "open_alerts": len(app_state.alert_engine.open_alerts),
    }


@router.get("/alerts")
async def alert_report(
    hours: int = Query(24, ge=1, le=720),
    severity: str | None = Query(None),
) -> dict:
    """Generate an alert history report."""
    from src.main import app_state

    alerts = app_state.db.list_alerts(severity=severity, limit=500)
    now = datetime.now(UTC)

    return {
        "report": "alert-history",
        "generated_at": now.isoformat(),
        "period_hours": hours,
        "total_alerts": len(alerts),
        "alerts": [
            {
                "id": a.id,
                "severity": a.severity,
                "asset_id": a.asset_id,
                "message": a.message,
                "status": a.status,
                "detected_at": a.detected_at.isoformat(),
            }
            for a in alerts
        ],
    }
