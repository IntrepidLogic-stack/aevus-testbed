"""
Aevus Testbed --- Incidents API Routes (Phase 4B, track 2)

Read-only. Clusters the retained alarm log (sqlite `alerts`, written every poll by
the scheduler) into INCIDENTS: a time-bounded degradation episode on one asset,
from the first alarm raise to the last recovery, with a root-cause label derived
from the alarms' own metric/message. Gives the Comms console durable live incident
history beyond the in-session open set. Correlations are not retained, so root cause
is the alarm-derived mechanism (labeled; never a fabricated correlation).
IL-9000: query-only, never writes or controls a device.

Contract (consumed by Aevus_Comms_Console.html incident source):
  GET /incidents?from=ISO&to=ISO&status=all|open|closed&limit=N
  -> {"incidents": [ {id, asset_id, asset_name, site, severity, kind, mechanism,
                      start, end|null, open, alarm_count, worst} ],
      "generated_at", "retained_since"}
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

router = APIRouter(prefix="/incidents", tags=["incidents"])

UTC = timezone.utc
# Gap (seconds) between an alarm and the running episode beyond which a NEW incident starts.
# Recurring bursts (e.g. RTU vibration every ~2 min) stay one incident; a quiet hour splits them.
_GAP_S = 45 * 60
_SEV_RANK = {"critical": 0, "warning": 1, "info": 2}

# Metric/message keyword -> human mechanism label. Derived from the alarm text the
# scheduler already writes ("SCADAPack 470: VIBRATION warning at 4.80 mm/s").
_MECH = [
    ("vibration", "Vibration / rotating-equipment stress"),
    ("fade margin", "Fade margin low (RF path)"),
    ("rssi", "RSSI low / path loss"),
    ("snr", "SNR low / interference"),
    ("temperature", "Thermal"),
    ("temp", "Thermal"),
    ("battery", "Power / battery"),
    ("voltage", "Power / supply"),
    ("pressure", "Process pressure excursion"),
    ("flow", "Process flow excursion"),
    ("level", "Tank / level excursion"),
    ("error", "Link errors / frame loss"),
    ("packet", "Link errors / frame loss"),
    ("reach", "Reachability / comms loss"),
    ("offline", "Device unreachable"),
    ("no response", "Device unreachable"),
    ("latency", "Comms latency"),
    ("chattering", "Chattering alarm (flapping)"),
]
_KIND = [
    ("vibration", "vibration"), ("fade", "rain"), ("rssi", "obstruct"), ("snr", "interf"),
    ("reach", "loss"), ("offline", "loss"), ("no response", "loss"), ("error", "flap"),
    ("packet", "flap"), ("chattering", "flap"),
]


def _mech_for(msg: str) -> str:
    m = (msg or "").lower()
    for kw, label in _MECH:
        if kw in m:
            return label
    return "Degradation"


def _kind_for(msg: str) -> str:
    m = (msg or "").lower()
    for kw, k in _KIND:
        if kw in m:
            return k
    return "live"


def _parse_iso(s):
    try:
        z = str(s).strip()
        if z.endswith("Z"):
            z = z[:-1] + "+00:00"
        d = datetime.fromisoformat(z)
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except Exception:
        return None


@router.get("")
async def list_incidents(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    status: str = Query("all", pattern="^(all|open|closed)$"),
    limit: int = Query(300, ge=1, le=1000),
) -> dict:
    """Cluster retained alarms into incidents overlapping the [from,to] window."""
    from src.main import app_state

    now = datetime.now(UTC)
    t_to = _parse_iso(to) or now
    t_from = _parse_iso(from_) or (t_to - timedelta(days=30))

    # asset_id -> location, for the site label
    loc = {}
    try:
        for a in app_state.db.list_assets():
            loc[a.id] = (getattr(a, "location", None) or "Unspecified")
    except Exception:
        pass

    raw = app_state.db.list_alerts(limit=2000)
    retained_since = None
    if raw:
        ds = min(a.detected_at for a in raw)
        retained_since = ds.astimezone(UTC).strftime("%Y-%m-%d")

    # group alarms by asset, sort by detected_at, cluster by gap
    by_asset: dict = {}
    for a in raw:
        by_asset.setdefault(a.asset_id, []).append(a)

    incidents = []
    for aid, alist in by_asset.items():
        alist.sort(key=lambda a: a.detected_at)
        cur = None

        def finalize(c):
            open_flag = c["_open"]
            end_dt = None if open_flag else c["_end"]
            return {
                "id": "LINC-" + aid + "-" + str(int(c["start"].timestamp())),
                "asset_id": aid,
                "asset_name": c["name"],
                "site": loc.get(aid, "Unspecified"),
                "severity": c["sev"],
                "kind": _kind_for(c["msg"]),
                "mechanism": _mech_for(c["msg"]),
                "start": c["start"].astimezone(UTC).isoformat(),
                "end": (end_dt.astimezone(UTC).isoformat() if end_dt else None),
                "open": open_flag,
                "alarm_count": c["n"],
                "worst": None,
            }

        for a in alist:
            a_open = (a.status != "resolved") or (a.resolved_at is None)
            a_end = a.resolved_at or now
            if cur is None:
                cur = {"start": a.detected_at, "_end": a_end, "_open": a_open, "sev": a.severity,
                       "name": a.asset_name, "msg": a.message, "n": 1}
                continue
            gap_ref = cur["_end"] if not cur["_open"] else a.detected_at   # open episode never "gaps"
            if (a.detected_at - gap_ref).total_seconds() > _GAP_S:
                incidents.append(finalize(cur))
                cur = {"start": a.detected_at, "_end": a_end, "_open": a_open, "sev": a.severity,
                       "name": a.asset_name, "msg": a.message, "n": 1}
            else:
                cur["n"] += 1
                if a_end > cur["_end"]:
                    cur["_end"] = a_end
                if a_open:
                    cur["_open"] = True
                if _SEV_RANK.get(a.severity, 9) < _SEV_RANK.get(cur["sev"], 9):
                    cur["sev"] = a.severity
                    cur["msg"] = a.message   # keep the message from the worst alarm
        if cur is not None:
            incidents.append(finalize(cur))

    # window overlap filter: incident touches [t_from, t_to]
    def in_window(i):
        s = _parse_iso(i["start"])
        e = _parse_iso(i["end"]) or now
        return e >= t_from and s <= t_to

    incidents = [i for i in incidents if in_window(i)]
    if status == "open":
        incidents = [i for i in incidents if i["open"]]
    elif status == "closed":
        incidents = [i for i in incidents if not i["open"]]

    # most recent first, open first
    incidents.sort(key=lambda i: (0 if i["open"] else 1, i["start"]), reverse=False)
    incidents.sort(key=lambda i: i["start"], reverse=True)
    incidents.sort(key=lambda i: 0 if i["open"] else 1)
    incidents = incidents[:limit]

    return {"incidents": incidents, "generated_at": now.isoformat(), "retained_since": retained_since}
