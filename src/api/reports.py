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
        asset_rows.append(
            {
                "id": a.id,
                "name": a.name,
                "type": a.type,
                "status": a.status,
                "health": a.health,
                "last_seen": a.last_seen.isoformat() if a.last_seen else None,
            }
        )

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


@router.get("/alarm-frequency")
async def alarm_frequency_report(
    hours: int = Query(24, ge=1, le=720),
) -> dict:
    """Alarm frequency report — count of alarms per hour."""
    from collections import defaultdict
    from src.main import app_state

    alerts = app_state.db.list_alerts(limit=1000)
    now = datetime.now(UTC)
    cutoff = now.timestamp() - (hours * 3600)

    hourly: dict[str, int] = defaultdict(int)
    by_severity: dict[str, int] = defaultdict(int)

    for a in alerts:
        ts = a.detected_at.timestamp()
        if ts < cutoff:
            continue
        hour_key = a.detected_at.strftime("%Y-%m-%d %H:00")
        hourly[hour_key] += 1
        by_severity[a.severity] = by_severity.get(a.severity, 0) + 1

    return {
        "report": "alarm-frequency",
        "generated_at": now.isoformat(),
        "period_hours": hours,
        "total_alarms": sum(hourly.values()),
        "by_severity": dict(by_severity),
        "hourly": [{"hour": k, "count": v} for k, v in sorted(hourly.items())],
    }


@router.get("/top-alarming")
async def top_alarming_report(
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    """Top alarming assets — which assets generate the most alarms."""
    from collections import Counter
    from src.main import app_state

    alerts = app_state.db.list_alerts(limit=1000)
    now = datetime.now(UTC)
    cutoff = now.timestamp() - (hours * 3600)

    asset_counts: Counter = Counter()
    asset_names: dict[str, str] = {}
    message_counts: Counter = Counter()

    for a in alerts:
        if a.detected_at.timestamp() < cutoff:
            continue
        asset_counts[a.asset_id] += 1
        asset_names[a.asset_id] = a.asset_name
        message_counts[a.message] += 1

    top_assets = [
        {"asset_id": aid, "asset_name": asset_names.get(aid, aid), "alarm_count": cnt}
        for aid, cnt in asset_counts.most_common(limit)
    ]
    top_messages = [
        {"message": msg, "count": cnt}
        for msg, cnt in message_counts.most_common(limit)
    ]

    return {
        "report": "top-alarming",
        "generated_at": now.isoformat(),
        "period_hours": hours,
        "top_assets": top_assets,
        "top_alarm_types": top_messages,
    }


@router.get("/uptime")
async def uptime_report(
    hours: int = Query(24, ge=1, le=720),
) -> dict:
    """Asset uptime report — online percentage per asset."""
    from src.main import app_state

    assets = app_state.db.list_assets()
    now = datetime.now(UTC)

    rows = []
    for a in assets:
        is_online = a.status in ("Good", "good", "online", "warning")
        last_seen_ago = None
        if a.last_seen:
            last_seen_ago = round((now - a.last_seen).total_seconds())

        rows.append({
            "asset_id": a.id,
            "name": a.name,
            "status": a.status,
            "health": a.health,
            "online": is_online,
            "last_seen_seconds_ago": last_seen_ago,
        })

    online_count = sum(1 for r in rows if r["online"])
    return {
        "report": "uptime",
        "generated_at": now.isoformat(),
        "period_hours": hours,
        "total_assets": len(rows),
        "online_count": online_count,
        "uptime_pct": round(online_count / len(rows) * 100, 1) if rows else 0,
        "assets": rows,
    }


@router.get("/journal")
async def journal_report(
    asset_id: str | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(100),
) -> dict:
    """Journal/audit trail report."""
    from src.main import app_state

    entries = app_state.db.list_journal(asset_id, category, limit)
    now = datetime.now(UTC)

    return {
        "report": "journal",
        "generated_at": now.isoformat(),
        "total_entries": len(entries),
        "entries": entries,
    }
