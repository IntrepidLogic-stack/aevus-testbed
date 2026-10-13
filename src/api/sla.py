"""
Aevus Testbed --- SLA / Compliance API (Phase 4C, track 2)

Read-only. Computes SLA attainment, error budget, and reliability metrics
(MTBF/MTTR) over the RETAINED incident record, mirroring the Comms console's
SLA & Compliance page math (slaForLink / slaAggregate, Aevus_Comms_Console.html)
so the numbers reconcile and the monthly SES digest can carry a one-line SLA
summary. IL-9000: query-only, never writes or controls a device.

Contract:
  GET /sla?from=ISO&to=ISO&avail_target=99.9&rf_target=99.5
  -> {period, targets, basis, enterprise, sites, digest_line, generated_at}

Basis -- why incident-derived, not telemetry-mean:
  Availability and RF-margin uptime are both derived from the retained incident
  record (the clustered alarm log src/api/incidents.py produces), NOT from a
  bucketed mean of the RSSI series. An earlier telemetry-mean basis reported
  100% uptime next to dozens of incidents, because a sub-minute fade is averaged
  away inside a multi-hour aggregateWindow(mean) bucket -- a misleading artifact.
  Deriving uptime from the same incidents that produce the incident COUNT makes
  the two surfaces reconcile by construction and matches the console's
  incident-derived slaForLink(). basis="incident-derived" is reported honestly
  (the incident record is built from measured alarms, but the uptime % is a
  derived downtime figure, not a directly-measured outage clock).

Semantics:
  - availability (reachability): per-link uptime = 1 - (summed duration of that
    link's reachability/comms-loss incidents [kind in AVAIL_KINDS], clamped to
    the window) / period; meaned across the group. Reachability loss and link
    flap/frame-error both reduce polls answered, so both debit availability.
  - rf_margin_uptime (path-fade margin): per-link uptime = 1 - (summed duration
    of that link's fade incidents [kind in FADE_KINDS: rain-fade / path
    obstruction] clamped to the window) / period; meaned across the group. This
    is the PATH / RSSI fade-margin objective; it deliberately does NOT fold in
    interference (SNR) or flap, which are tracked separately -- the name is
    RSSI/path-margin uptime, not overall RF health.
  - MTBF = (period_hours * link_count) / link-affecting incident count (kind in
    LINK_KINDS). Warnings that are not comms-link failures (vibration, thermal,
    process excursions) are excluded from the failure count so MTBF is not
    overstated; they still appear in the total `incidents` figure. Fleet
    link-hours per link-incident.
  - MTTR = pooled mean of CLOSED incident durations across the group (concatenate
    every closed-incident duration, then mean -- NOT a mean of per-link means).
    Mean time to restore (detect + respond + repair). Null with no closed incidents.
  - error budget per objective: allowed=(1-target/100)*period;
    consumed=(1-actual/100)*period; remaining=allowed-consumed (minutes).

Incidents are the SAME clustering src/api/incidents.py produces -- list_incidents()
is called in-process (no self-HTTP call) and filtered to the RF links in scope.
The RF link set is the set of assets reporting retained RSSI over the window
(one query_rssi_matrix() call, used only to scope the link set -- its sample
values are not used for any uptime percentage).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from src.api.history import _rollup_step
from src.api.incidents import list_incidents

router = APIRouter(prefix="/sla", tags=["sla"])

UTC = timezone.utc
_MIN_MS = 60_000.0
_HOUR_MS = 3_600_000.0

# Incident kind -> which SLA objective its downtime debits. Kinds come from
# incidents.py _kind_for(): vibration / rain / obstruct / interf / loss / flap / live.
AVAIL_KINDS = {"loss", "flap"}          # reachability: comms loss + link flap/frame-error
FADE_KINDS = {"rain", "obstruct"}       # path fade-margin: rain-fade + path obstruction
LINK_KINDS = AVAIL_KINDS | FADE_KINDS | {"interf"}  # link-affecting, for MTBF failure count


def _parse_iso(s: str | None):
    """Best-effort ISO-8601 parse (accepts trailing 'Z'); None on failure."""
    if not s:
        return None
    try:
        z = str(s).strip()
        if z.endswith("Z"):
            z = z[:-1] + "+00:00"
        d = datetime.fromisoformat(z)
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except Exception:
        return None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _fmt_hours(h: float | None) -> str:
    """Human duration from hours, matching the console's fmtDurMs() bands."""
    if h is None:
        return "n/a"
    if h >= 720:
        return f"{h / 720:.1f} mo"
    if h >= 48:
        return f"{h / 24:.1f} d"
    if h >= 1:
        return f"{h:.1f} h"
    return f"{max(1, round(h * 60))} min"


def _fmt_minutes(m: float | None) -> str:
    if m is None:
        return "n/a"
    return _fmt_hours(m / 60.0)


@router.get("")
async def sla_summary(
    from_: str | None = Query(None, alias="from", description="ISO-8601 window start; default 30d ago"),
    to: str | None = Query(None, description="ISO-8601 window end; default now"),
    avail_target: float = Query(99.9, ge=0, le=100, description="Availability SLA target, percent"),
    rf_target: float = Query(99.5, ge=0, le=100, description="RF-margin uptime SLA target, percent"),
) -> dict:
    """SLA attainment + MTBF/MTTR over the retained window, for the SES digest."""
    from src.main import app_state

    now = datetime.now(UTC)
    t_to = _parse_iso(to) or now
    t_from = _parse_iso(from_) or (t_to - timedelta(days=30))
    if t_to <= t_from:
        t_from = t_to - timedelta(days=30)
    period_hours = (t_to - t_from).total_seconds() / 3600.0
    period_ms = period_hours * _HOUR_MS

    from_iso = t_from.isoformat()
    to_iso = t_to.isoformat()

    # --- RF link set: assets reporting retained RSSI over the window. The matrix
    # is used ONLY to scope which assets are RF links (and the link count for
    # MTBF); its sample VALUES do not feed any uptime percentage. ---
    span = app_state.influx.span_ms(from_iso, to_iso)
    step = _rollup_step(span) if span and span > 0 else 3600
    matrix = app_state.influx.query_rssi_matrix(from_iso, to_iso, step) if span and span > 0 else []

    rf_links = sorted({row["asset_id"] for row in matrix})
    rf_set = set(rf_links)

    # asset_id -> site, for grouping (same lookup history.py/incidents.py use)
    loc: dict[str, str] = {}
    try:
        for a in app_state.db.list_assets():
            loc[a.id] = getattr(a, "location", None) or "Unspecified"
    except Exception:
        pass

    # --- Incidents: reuse incidents.py's clustering in-process (no self-HTTP) ---
    inc_payload = await list_incidents(from_=from_iso, to=to_iso, status="all", limit=1000)
    all_incidents = inc_payload.get("incidents", [])
    incidents = [i for i in all_incidents if i["asset_id"] in rf_set] if rf_set else []

    # --- Incident-derived downtime per link, split by objective. Clustered
    # episodes are time-disjoint per asset, so summing clamped durations is safe. ---
    avail_down_ms: dict[str, float] = defaultdict(float)
    fade_down_ms: dict[str, float] = defaultdict(float)
    for i in incidents:
        s = _parse_iso(i.get("start"))
        e = _parse_iso(i.get("end")) or now
        if s is None:
            continue
        s = max(s, t_from)
        e = min(e, t_to)
        if e <= s:
            continue
        dur = (e - s).total_seconds() * 1000.0
        aid = i["asset_id"]
        kind = i.get("kind")
        if kind in AVAIL_KINDS:
            avail_down_ms[aid] += dur
        if kind in FADE_KINDS:
            fade_down_ms[aid] += dur

    def _uptime_pct(down_ms: float) -> float:
        if period_ms <= 0:
            return 100.0
        return _clamp(100.0 * (period_ms - min(down_ms, period_ms)) / period_ms, 0.0, 100.0)

    per_asset_avail = {aid: _uptime_pct(avail_down_ms.get(aid, 0.0)) for aid in rf_links}
    per_asset_rf = {aid: _uptime_pct(fade_down_ms.get(aid, 0.0)) for aid in rf_links}

    def _closed_durations_ms(incs: list[dict]) -> list[float]:
        durs = []
        for i in incs:
            if i.get("open"):
                continue
            s = _parse_iso(i.get("start"))
            e = _parse_iso(i.get("end")) or now
            if s and e > s:
                durs.append((e - s).total_seconds() * 1000.0)
        return durs

    def _group_metrics(asset_ids: list[str], incs: list[dict]) -> dict:
        avail_vals = [per_asset_avail[a] for a in asset_ids if a in per_asset_avail]
        rf_vals = [per_asset_rf[a] for a in asset_ids if a in per_asset_rf]
        avail = sum(avail_vals) / len(avail_vals) if avail_vals else None
        rf = sum(rf_vals) / len(rf_vals) if rf_vals else None
        n_inc = len(incs)
        n_fail = sum(1 for i in incs if i.get("kind") in LINK_KINDS)
        mtbf_hours = (
            (period_hours * len(asset_ids) / n_fail) if n_fail > 0 and asset_ids else None
        )
        closed = _closed_durations_ms(incs)
        mttr_minutes = (sum(closed) / len(closed) / _MIN_MS) if closed else None
        return {
            "availability": round(avail, 3) if avail is not None else None,
            "availability_met": bool(avail is not None and avail >= avail_target),
            "rf_margin_uptime": round(rf, 3) if rf is not None else None,
            "rf_met": bool(rf is not None and rf >= rf_target),
            "mtbf_hours": round(mtbf_hours, 2) if mtbf_hours is not None else None,
            "mttr_minutes": round(mttr_minutes, 2) if mttr_minutes is not None else None,
            "incidents": n_inc,
            "link_failures": n_fail,
            "links": len(asset_ids),
        }

    def _error_budget(actual: float | None, target: float) -> dict | None:
        if actual is None:
            return None
        allowed_ms = (1 - target / 100) * period_ms
        consumed_ms = (1 - actual / 100) * period_ms
        return {
            "allowed_minutes": round(allowed_ms / _MIN_MS, 2),
            "consumed_minutes": round(consumed_ms / _MIN_MS, 2),
            "remaining_minutes": round((allowed_ms - consumed_ms) / _MIN_MS, 2),
        }

    enterprise = _group_metrics(rf_links, incidents)
    enterprise["error_budget"] = {
        "availability": _error_budget(enterprise["availability"], avail_target),
        "rf_margin_uptime": _error_budget(enterprise["rf_margin_uptime"], rf_target),
    }

    by_site: dict[str, list[str]] = {}
    for aid in rf_links:
        by_site.setdefault(loc.get(aid, "Unspecified"), []).append(aid)

    sites = []
    for site, members in sorted(by_site.items()):
        member_set = set(members)
        site_incidents = [i for i in incidents if i["asset_id"] in member_set]
        row = _group_metrics(members, site_incidents)
        row["site"] = site
        sites.append(row)

    def _human_pct(v: float | None) -> str:
        return f"{v:.2f}%" if v is not None else "n/a"

    def _met_word(met: bool, v: float | None) -> str:
        return "MET" if (v is not None and met) else ("MISSED" if v is not None else "n/a")

    period_days = round(period_hours / 24.0, 1)
    period_label = f"{int(period_days)}d" if period_days == int(period_days) else f"{period_days}d"
    digest_line = (
        f"SLA ({period_label}): "
        f"availability {_human_pct(enterprise['availability'])} "
        f"({_met_word(enterprise['availability_met'], enterprise['availability'])}), "
        f"RF-margin uptime {_human_pct(enterprise['rf_margin_uptime'])} "
        f"({_met_word(enterprise['rf_met'], enterprise['rf_margin_uptime'])}), "
        f"{enterprise['incidents']} incidents, "
        f"MTBF {_fmt_hours(enterprise['mtbf_hours'])}, "
        f"MTTR {_fmt_minutes(enterprise['mttr_minutes'])}"
    )

    return {
        "period": {"from": from_iso, "to": to_iso, "hours": round(period_hours, 2)},
        "targets": {"availability": avail_target, "rf_margin_uptime": rf_target},
        "basis": "incident-derived",
        "enterprise": enterprise,
        "sites": sites,
        "digest_line": digest_line,
        "generated_at": now.isoformat(),
    }
