"""
Aevus Testbed --- Health API Routes
"""

from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/summary")
async def health_summary() -> dict:
    """Overall fleet health summary and per-class breakdown."""
    from src.main import app_state

    assets = app_state.db.list_assets()
    total = len(assets)
    if total == 0:
        return {"total_assets": 0, "avg_health": None, "by_status": {}, "by_type": {}}

    scores = [a.health for a in assets if a.health is not None]
    avg = round(sum(scores) / len(scores)) if scores else None

    by_status: dict[str, int] = {}
    by_type: dict[str, dict] = {}

    for a in assets:
        by_status[a.status] = by_status.get(a.status, 0) + 1

        if a.type not in by_type:
            by_type[a.type] = {"count": 0, "scores": []}
        by_type[a.type]["count"] += 1
        if a.health is not None:
            by_type[a.type]["scores"].append(a.health)

    type_summary = {}
    for t, info in by_type.items():
        s = info["scores"]
        type_summary[t] = {
            "count": info["count"],
            "avg_health": round(sum(s) / len(s)) if s else None,
        }

    return {
        "total_assets": total,
        "avg_health": avg,
        "by_status": by_status,
        "by_type": type_summary,
        "open_alerts": len(app_state.alert_engine.open_alerts),
        "ws_clients": app_state.ws_clients,
    }


@router.get("/trend")
async def health_trend(
    asset_id: str | None = Query(None),
    metric: str = Query("cpu_load"),
    hours: int = Query(24, ge=1, le=720),
) -> list[dict]:
    """Time-series trend data for a specific metric."""
    from src.main import app_state

    if asset_id is None:
        # Fleet aggregate: return trends across all assets
        assets = app_state.db.list_assets()
        all_points: list[dict] = []
        for asset in assets:
            points = app_state.influx.query_trend(asset.id, metric, hours)
            for p in points:
                p["asset_id"] = asset.id
            all_points.extend(points)
        all_points.sort(key=lambda p: p.get("time", ""))
        return all_points
    return app_state.influx.query_trend(asset_id, metric, hours)


@router.get("/ping")
async def health_ping():
    """Lightweight health check for uptime monitoring and deploy verification."""
    return {"status": "ok", "service": "aevus", "version": "0.1.0"}
