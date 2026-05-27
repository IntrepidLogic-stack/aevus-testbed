"""
Aevus Testbed --- Diagnostics API Routes
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("/fleet")
async def fleet_diagnostics() -> dict:
    """Equipment fleet breakdown by vendor and type."""
    from src.main import app_state

    assets = app_state.db.list_assets()

    by_vendor: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_protocol: dict[str, int] = {}

    for a in assets:
        by_vendor[a.vendor] = by_vendor.get(a.vendor, 0) + 1
        by_type[a.type] = by_type.get(a.type, 0) + 1
        by_protocol[a.protocol] = by_protocol.get(a.protocol, 0) + 1

    return {
        "total": len(assets),
        "by_vendor": by_vendor,
        "by_type": by_type,
        "by_protocol": by_protocol,
    }


@router.get("/signals")
async def signal_diagnostics() -> list[dict]:
    """Predictive signal trends per asset (latest vitals snapshot)."""
    from src.main import app_state

    assets = app_state.db.list_assets()
    signals = []
    for a in assets:
        signals.append(
            {
                "asset_id": a.id,
                "asset_name": a.name,
                "type": a.type,
                "health": a.health,
                "status": a.status,
                "vitals_count": len(a.vitals),
                "last_seen": a.last_seen.isoformat() if a.last_seen else None,
            }
        )
    return signals
