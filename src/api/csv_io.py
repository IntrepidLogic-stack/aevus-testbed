"""Aevus API — CSV Import/Export for Asset Registry."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, File, UploadFile
from starlette.responses import StreamingResponse

router = APIRouter(prefix="/csv", tags=["csv"])


def _get_db():
    from src.main import app_state
    return app_state.db


COLUMNS = [
    "id", "type", "status", "name", "location", "health",
    "last_seen", "vendor", "model", "firmware", "ip_address",
    "mac_address", "protocol", "poll_interval",
]


@router.get("/export")
async def export_csv():
    """Export all assets as a CSV download."""
    db = _get_db()
    assets = db.list_assets()

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS)
    writer.writeheader()
    for a in assets:
        writer.writerow({
            "id": a.id,
            "type": a.type,
            "status": a.status,
            "name": a.name,
            "location": a.location,
            "health": a.health,
            "last_seen": a.last_seen.isoformat() if a.last_seen else "",
            "vendor": a.vendor,
            "model": a.model,
            "firmware": a.firmware or "",
            "ip_address": a.ip_address or "",
            "mac_address": a.mac_address or "",
            "protocol": a.protocol,
            "poll_interval": a.poll_interval,
        })

    buf.seek(0)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=aevus_assets_{ts}.csv"},
    )


@router.post("/import")
async def import_csv(file: UploadFile = File(...)):
    """Import assets from a CSV file. Upserts into asset_registry."""
    from src.models.asset import Asset

    db = _get_db()
    content = (await file.read()).decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))

    imported = 0
    skipped = 0
    errors = []

    for i, row in enumerate(reader, start=2):
        asset_id = (row.get("id") or "").strip()
        name = (row.get("name") or "").strip()
        atype = (row.get("type") or "").strip()

        if not asset_id or not name or not atype:
            missing = [f for f in ("id", "name", "type") if not (row.get(f) or "").strip()]
            errors.append("Row {}: missing required field(s): {}".format(i, ", ".join(missing)))
            skipped += 1
            continue

        try:
            health_val = row.get("health")
            health = int(health_val) if health_val and health_val.strip() else None

            poll_val = row.get("poll_interval")
            poll_interval = int(poll_val) if poll_val and poll_val.strip() else 30

            asset = Asset(
                id=asset_id,
                type=atype,
                status=(row.get("status") or "unknown").strip(),
                name=name,
                location=(row.get("location") or "Lab Cabinet").strip(),
                health=health,
                vendor=(row.get("vendor") or "Unknown").strip(),
                model=(row.get("model") or "Unknown").strip(),
                firmware=(row.get("firmware") or "").strip() or None,
                ip_address=(row.get("ip_address") or "").strip() or None,
                mac_address=(row.get("mac_address") or "").strip() or None,
                protocol=(row.get("protocol") or "snmp").strip(),
                poll_interval=poll_interval,
            )
            db.upsert_asset(asset)
            imported += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")
            skipped += 1

    return {"imported": imported, "skipped": skipped, "errors": errors}
