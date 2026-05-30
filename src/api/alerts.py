"""
Aevus Testbed --- Alert API Routes
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.models.alert import Alert

if TYPE_CHECKING:
    from datetime import datetime

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ---- Shelve request / response models (ISA-18.2 §11) -----------------------


class ShelveRequest(BaseModel):
    """Operator request to shelve an alarm key for a bounded duration."""

    asset_id: str = Field(..., description="Asset whose alarm to shelve, e.g. 'RAD-01'")
    metric_label: str = Field(
        ...,
        description="Metric or event-type label, e.g. 'RSSI' or 'FIRMWARE_CHANGED'",
    )
    duration_s: int = Field(
        1800,
        ge=60,
        le=28800,
        description="Shelf duration, 60s–8h per ISA-18.2 §11.4",
    )
    reason: str = Field(
        "manual",
        max_length=200,
        description="Operator-supplied justification, captured in audit log",
    )
    operator: str = Field(
        "system",
        max_length=64,
        description="Who initiated the shelve (free-text until auth is wired)",
    )


class ShelveResponse(BaseModel):
    asset_id: str
    metric_label: str
    expires_at: datetime
    audit_id: int


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


@router.post("/{alert_id}/resolve", response_model=Alert)
async def resolve_alert(alert_id: str) -> Alert:
    """Resolve an open or acknowledged alert."""
    from src.main import app_state

    alert = app_state.alert_engine.resolve(alert_id, db=app_state.db)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found or already resolved")

    app_state.db.save_alert(alert)
    return alert


# ---- Shelve / unshelve (ISA-18.2 §11) -------------------------------------


@router.post("/shelve", response_model=ShelveResponse)
async def shelve_alarm(req: ShelveRequest) -> ShelveResponse:
    """Shelve an (asset_id, metric_label) alarm key for a bounded duration.

    While shelved, the AlertEngine will not fire NEW alerts for this key.
    Existing open alerts are NOT auto-resolved — operator handles those via
    ack/resolve. Audit-logged per ISA-18.2 §11.4.
    """
    from src.main import app_state

    expires_at = app_state.alert_engine.shelve(
        asset_id=req.asset_id,
        metric_label=req.metric_label,
        duration_s=req.duration_s,
        reason=req.reason,
    )
    audit_id = app_state.db.log_shelve_action(
        asset_id=req.asset_id,
        metric_label=req.metric_label,
        action="shelve",
        duration_s=req.duration_s,
        expires_at=expires_at.isoformat(),
        reason=req.reason,
        operator=req.operator,
    )
    return ShelveResponse(
        asset_id=req.asset_id,
        metric_label=req.metric_label,
        expires_at=expires_at,
        audit_id=audit_id,
    )


@router.post("/unshelve")
async def unshelve_alarm(
    asset_id: str = Query(...),
    metric_label: str = Query(...),
    operator: str = Query("system"),
) -> dict:
    """Remove an active shelf early. No-op if the key wasn't shelved."""
    from src.main import app_state

    was_shelved = app_state.alert_engine.is_shelved(asset_id, metric_label)
    if was_shelved:
        # Force-expire by setting expiry to now
        from datetime import UTC, datetime
        app_state.alert_engine._shelved_until[(asset_id, metric_label)] = datetime.now(UTC)
        # And the next is_shelved() call will clean it up
        app_state.alert_engine.is_shelved(asset_id, metric_label)

    audit_id = app_state.db.log_shelve_action(
        asset_id=asset_id,
        metric_label=metric_label,
        action="unshelve",
        operator=operator,
        reason="operator unshelve",
    )
    return {
        "asset_id": asset_id,
        "metric_label": metric_label,
        "was_shelved": was_shelved,
        "audit_id": audit_id,
    }


@router.get("/shelved")
async def list_shelved() -> list[dict]:
    """List all currently-shelved (asset_id, metric_label) keys + expiry."""
    from src.main import app_state

    return [
        {
            "asset_id": asset_id,
            "metric_label": metric,
            "expires_at": expiry.isoformat(),
        }
        for (asset_id, metric), expiry in app_state.alert_engine._shelved_until.items()
    ]


@router.get("/shelve-audit")
async def list_shelve_audit(
    asset_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict]:
    """Audit log of all shelve / unshelve / expire actions."""
    from src.main import app_state

    return app_state.db.list_shelve_audit(asset_id=asset_id, limit=limit)
