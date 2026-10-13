"""
Aevus Testbed --- History API Routes (Phase 4A)

Read-only retained-telemetry history for the Comms console Trends page. Serves
the three continuously-measured RF scalars (fade margin / SNR / RSSI) straight
from InfluxDB, bucketed to the console's requested step. Metrics that are not
retained as raw series (throughput, percent-good polls, packet-error rate) are
omitted; the console renders those lanes as honest "no retained history" rather
than showing a fabricated number. IL-9000: query-only, never writes or controls.

Contract (matches aevus_comms_prototype/Aevus_Comms_Console.html, historyFor):
  GET /history/links?ids=a,b&metrics=margin,snr,rssi&from=ISO&to=ISO&step=3600
      -> {"series": {asset_id: {hk: [{"t": epoch_ms, "v": num}]}}, "retained_since": "YYYY-MM-DD"}
  GET /history/rollup?scope=enterprise|site&from=ISO&to=ISO
      -> {"groups": [{"key","label","links":[ids],
                      "avail":[{t,v}], "marginMean":[{t,v}], "marginWorst":[{t,v}]}],
          "retained_since": "YYYY-MM-DD"}
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.config import settings

router = APIRouter(prefix="/history", tags=["history"])

# Retained RF scalars. RSSI and SNR are written every poll; fade MARGIN is a pure
# transform of RSSI (margin = rssi - receiver_sensitivity, the same derivation the
# normalizer used when it populated the fade_margin series), so it is derived at
# query time from the retained RSSI rather than read from a (no-longer-written)
# fade_margin series. Metrics the console asks for that are NOT retained
# (throughput, percent-good, packet-error) are omitted -> honest no-history lane.
_SUPPORTED_HK = {"margin", "snr", "rssi"}

_DAY_MS = 86400000


def _sensitivity_dbm() -> float:
    """Receiver sensitivity used to turn measured RSSI into fade margin."""
    try:
        s = getattr(settings, "radio_sensitivity_dbm", None)
        s = float(s)
        # guard a mis-set/zero config: a real sensitivity is a strong negative dBm
        return s if s < -30 else -95.0
    except (TypeError, ValueError):
        return -95.0


def _rollup_step(span_ms: int) -> int:
    """Mirror the console's bucket cadence: 5 min (<=2d), 1 h (<=10d), else 6 h.

    The console does not send a step for rollups, so the server picks the same
    one the synthetic rollup uses, keeping bucket counts (~150-300) comparable.
    """
    if span_ms <= 2 * _DAY_MS:
        return 300
    if span_ms <= 10 * _DAY_MS:
        return 3600
    return 21600


@router.get("/links")
async def history_links(
    ids: str = Query(..., description="comma-separated asset ids"),
    metrics: str = Query("margin,snr,rssi", description="comma-separated console signal keys"),
    from_: str = Query(..., alias="from", description="ISO-8601 start"),
    to: str = Query(..., description="ISO-8601 end"),
    step: int = Query(3600, ge=30, le=86400, description="bucket size in seconds"),
) -> dict:
    """Per-link measured history for the requested RF scalars, bucketed to step."""
    from src.main import app_state

    asset_ids = [s.strip() for s in ids.split(",") if s.strip()][:40]
    requested = [s.strip() for s in metrics.split(",") if s.strip()]
    hks = {m for m in requested if m in _SUPPORTED_HK}
    # Default to all three ONLY when no metrics were named at all. If metrics were
    # named but none are retained, return nothing (honest no-history for each).
    if not requested:
        hks = {"margin", "snr", "rssi"}
    if not hks:
        return {"series": {}, "retained_since": app_state.influx.retained_since()}

    # RSSI backs both the rssi lane and the derived margin lane; fetch it once.
    influx_metrics = []
    if "snr" in hks:
        influx_metrics.append("snr")
    if "rssi" in hks or "margin" in hks:
        influx_metrics.append("rssi")

    raw = app_state.influx.query_links(asset_ids, influx_metrics, from_, to, step)
    sens = _sensitivity_dbm()

    series: dict = {}
    for aid, by_metric in raw.items():
        out: dict = {}
        if "snr" in hks and "snr" in by_metric:
            out["snr"] = by_metric["snr"]
        if "rssi" in hks and "rssi" in by_metric:
            out["rssi"] = by_metric["rssi"]
        if "margin" in hks and "rssi" in by_metric:
            out["margin"] = [{"t": p["t"], "v": round(p["v"] - sens, 1)} for p in by_metric["rssi"]]
        if out:
            series[aid] = out

    return {"series": series, "retained_since": app_state.influx.retained_since()}


@router.get("/rollup")
async def history_rollup(
    scope: str = Query("enterprise", description="enterprise | site"),
    from_: str = Query(..., alias="from", description="ISO-8601 start"),
    to: str = Query(..., description="ISO-8601 end"),
) -> dict:
    """Group rollup: reachability + mean / worst fade margin per group, bucketed.

    Availability is link reachability (fade margin reported this bucket / RF links
    in the group), tracked separately from fade-margin health, matching the
    console's "reachability (polls answered)" caption.
    """
    from src.main import app_state

    span = app_state.influx.span_ms(from_, to)
    if span is None or span <= 0:
        return {"groups": [], "retained_since": app_state.influx.retained_since()}
    step = _rollup_step(span)

    matrix = app_state.influx.query_rssi_matrix(from_, to, step)  # [{asset_id,t,v=rssi}]
    if not matrix:
        return {"groups": [], "retained_since": app_state.influx.retained_since()}

    # asset_id -> location, for site grouping
    loc: dict = {}
    try:
        for a in app_state.db.list_assets():
            loc[a.id] = getattr(a, "location", None) or "Unspecified"
    except Exception:  # noqa: S110
        pass

    # Fade margin = RSSI - receiver sensitivity (same transform as the per-link lane).
    sens = _sensitivity_dbm()
    buckets = sorted({row["t"] for row in matrix})
    rf_assets = sorted({row["asset_id"] for row in matrix})
    cell = {(row["t"], row["asset_id"]): round(row["v"] - sens, 1) for row in matrix}

    def group_key(aid: str) -> str:
        return loc.get(aid, "Unspecified") if scope == "site" else "ENT"

    groups_map: dict = {}
    for aid in rf_assets:
        groups_map.setdefault(group_key(aid), []).append(aid)

    out_groups = []
    for key, members in groups_map.items():
        total = len(members)
        avail, mean_s, worst_s = [], [], []
        for t in buckets:
            vals = [cell[(t, a)] for a in members if (t, a) in cell]
            up = len(vals)
            avail.append({"t": t, "v": round(up / total * 100, 2) if total else None})
            if vals:
                mean_s.append({"t": t, "v": round(sum(vals) / len(vals), 1)})
                worst_s.append({"t": t, "v": round(min(vals), 1)})
            else:
                mean_s.append({"t": t, "v": None})
                worst_s.append({"t": t, "v": None})
        label = key if scope == "site" else "Enterprise"
        out_groups.append(
            {
                "key": key,
                "label": label,
                "links": members,
                "avail": avail,
                "marginMean": mean_s,
                "marginWorst": worst_s,
            }
        )

    out_groups.sort(key=lambda g: g["label"])
    return {"groups": out_groups, "retained_since": app_state.influx.retained_since()}
