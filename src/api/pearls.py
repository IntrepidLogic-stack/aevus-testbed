"""Rickerson Scale pearl API (P0b).

Returns ordered pearl lists for the edge→operator data path. Each pearl is
{pearl_id, label, asset_id, score (0-100|null), status, last_update,
drill_url}. Sourced from src.engine.pearl_score (trade-secret normalization).

SECURITY: raw input vitals are NEVER echoed back in this response. The
score is the only signal exposed. Anyone sampling this endpoint cannot
reverse-engineer the curves from the output alone.

Pearls layout (per spec):
  1. EFM/RTU/PLC      → first 'rtu' or 'efm' asset
  2. Subscriber radio → 'radio' with role=SLAVE (RAD-02 in testbed)
  3. Master radio     → 'radio' with role=MASTER (RAD-01 in testbed)
  4. Plant router     → 'router' (RTR-01)
  5. Aggregation      → 'switch' (SW-01 — proxies I/O server in testbed,
                        becomes Wonderware/Ignition in a Kinetik deploy)
  6. SCADA host       → 'edge' (EDGE-01) or scada_host
  7. VPN              → hidden if not present
  8. HMI node         → browser heartbeat (hidden until P0d ships)

For the collimated grid: 1 real tower (KILLDEER) + 2 simulated peer towers
(EDDY-COUNTY, CULBERSON) with dashed-border styling on the frontend so the
demo hits Rickerson's ≥3-tower acceptance criterion without faking telemetry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query

from src.engine.pearl_score import score_asset

router = APIRouter(prefix="/pearls", tags=["pearls"])


# ── Pearl chain definitions ────────────────────────────────────────────
# (pearl_id, label, asset_resolver) — asset_resolver pulls the right asset
# from the live registry. Resolvers return None if absent → pearl is hidden.
def _find_radio_master(assets: list) -> Any | None:
    for a in assets:
        if a.type == "radio":
            for v in a.vitals or []:
                if v.label == "ROLE" and v.value and "MASTER" in v.value.upper():
                    return a
    # Fallback to known wiring
    for a in assets:
        if a.id == "RAD-01":
            return a
    return None


def _find_radio_slave(assets: list) -> Any | None:
    for a in assets:
        if a.type == "radio":
            for v in a.vitals or []:
                if v.label == "ROLE" and v.value and "SLAVE" in v.value.upper():
                    return a
    for a in assets:
        if a.id == "RAD-02":
            return a
    return None


def _find_by_type(assets: list, t: str) -> Any | None:
    for a in assets:
        if a.type == t:
            return a
    return None


def _find_efm_rtu(assets: list) -> Any | None:
    """EFM/RTU/PLC slot. Prefer a REAL-sourced (relay/Modbus/DNP3/SNMP) RTU or
    EFM over a seeded simulator — so once the live SCADAPack 470 starts
    relaying over Modbus, this pearl reflects the real device instead of the
    demo EFM. Falls back to first rtu, then first efm (pre-existing behavior)
    when no real-sourced device is present."""
    from src.api.relay_overlay import is_real_sourced

    candidates = [a for a in assets if a.type in ("rtu", "efm")]
    real = [a for a in candidates if is_real_sourced(a)]
    if real:
        # Prefer a real rtu over a real efm if both exist
        return next((a for a in real if a.type == "rtu"), real[0])
    rtu = _find_by_type(assets, "rtu")
    return rtu or _find_by_type(assets, "efm")


def _find_by_id(assets: list, asset_id: str) -> Any | None:
    for a in assets:
        if a.id == asset_id:
            return a
    return None


KILLDEER_CHAIN = [
    ("efm_rtu", "EFM/RTU/PLC", _find_efm_rtu),
    ("sub_radio", "Subscriber Radio", _find_radio_slave),
    ("mst_radio", "Master Radio", _find_radio_master),
    ("plant_rtr", "Plant Router", lambda a: _find_by_type(a, "router")),
    ("agg", "Aggregation", lambda a: _find_by_type(a, "switch")),
    ("scada_host", "SCADA Host", lambda a: _find_by_id(a, "EDGE-01") or _find_by_type(a, "edge")),
    # VPN + HMI hidden until present (spec allows hiding absent pearls)
]


def _drill_for(asset_id: str | None, asset_type: str | None) -> str:
    """Where clicking a pearl takes the operator. Same-page anchor when
    possible so we don't blow context (SCADA op feedback)."""
    if asset_id is None:
        return ""
    type_to_page = {
        "radio": "#radio",
        "router": "#network",
        "switch": "#network",
        "rtu": "#sites",
        "efm": "#sites",
        "edge": "#diagnostics",
    }
    page = type_to_page.get(asset_type or "", "#overview")
    return f"{page}?asset={asset_id}"


def _last_update_iso(asset: Any) -> str | None:
    ls = getattr(asset, "last_seen", None)
    if isinstance(ls, datetime):
        return ls.isoformat()
    return None


def _pearl_for(pearl_id: str, label: str, asset: Any | None) -> dict:
    """Render one pearl. SECURITY: never include raw vitals in this dict."""
    if asset is None:
        return {
            "pearl_id": pearl_id,
            "label": label,
            "asset_id": None,
            "score": None,
            "status": "offline",
            "last_update": None,
            "drill_url": "",
        }
    score, status = score_asset(asset)
    return {
        "pearl_id": pearl_id,
        "label": label,
        "asset_id": asset.id,
        "asset_label": asset.name,
        "score": score,
        "status": status,
        "last_update": _last_update_iso(asset),
        "drill_url": _drill_for(asset.id, asset.type),
    }


# ── Simulated peer towers ──────────────────────────────────────────────
# Per umbrella session decision: 1 real + 2 SIM towers to hit ≥3 acceptance.
# These return deterministic-pseudo scores so demo telemetry looks alive but
# is clearly labeled SIM on the frontend. NOT presented as real measurements.
def _sim_pearl(pearl_id: str, label: str, score: int | None, status_override: str | None = None) -> dict:
    return {
        "pearl_id": pearl_id,
        "label": label,
        "asset_id": None,
        "asset_label": "(simulated peer)",
        "score": score,
        "status": status_override
        or (
            "good"
            if score is not None and score >= 60
            else "warn"
            if score is not None and score >= 30
            else "bad"
            if score is not None
            else "offline"
        ),
        "last_update": datetime.now(UTC).isoformat(),
        "drill_url": "",
        "simulated": True,
    }


def _build_sim_tower(name: str, profile: str) -> dict:
    """Build a simulated tower's pearl chain. `profile` drives the story
    we tell with the chain — 'healthy', 'degraded', 'critical'."""
    if profile == "healthy":
        scores = [94, 91, 89, 95, 97, 99]
    elif profile == "degraded":
        scores = [88, 86, 52, 91, 96, 98]  # master radio degraded
    else:  # critical
        scores = [82, 28, 24, 78, 90, 95]  # sub + master red
    pearls = []
    for (pid, label, _), sc in zip(KILLDEER_CHAIN, scores, strict=True):
        pearls.append(_sim_pearl(pid, label, sc))
    return {
        "tower_id": name.lower().replace(" ", "-"),
        "tower_label": name,
        "simulated": True,
        "header_status": "bad" if profile == "critical" else "warn" if profile == "degraded" else "good",
        "pearls": pearls,
    }


# ── Endpoints ──────────────────────────────────────────────────────────
@router.get("/killdeer")
async def killdeer_pearls() -> dict:
    """Single tower: Killdeer Field testbed. Real telemetry only."""
    from src.api.relay_overlay import apply_relay_overlay
    from src.main import app_state

    assets = apply_relay_overlay(app_state.db.list_assets())
    pearls = []
    worst = "good"
    for pearl_id, label, resolver in KILLDEER_CHAIN:
        asset = resolver(assets)
        p = _pearl_for(pearl_id, label, asset)
        pearls.append(p)
        if p["status"] == "bad":
            worst = "bad"
        elif p["status"] == "warn" and worst == "good":
            worst = "warn"
    return {
        "tower_id": "killdeer",
        "tower_label": "Killdeer Field",
        "simulated": False,
        "header_status": worst,
        "pearls": pearls,
    }


# ── Demo drill — radio-fade simulation (P0d) ──────────────────────────
# When triggered, downshift one of Killdeer's pearls for `duration` seconds
# so the show-back Loom can demo yellow→red transition + upstream-tower
# header turning yellow. State lives in-memory (acceptable for demo path).
_drill_state: dict = {"active_until": None, "pearl_id": None, "force_status": "bad"}


@router.post("/drill/radio-fade")
async def drill_radio_fade(duration: int = Query(60, ge=10, le=300), pearl_id: str = Query("sub_radio")) -> dict:
    """Demo-only: force a Killdeer pearl into bad status for N seconds.
    Loom narration: 'Watch the sub-radio pearl go red — upstream tower
    header turns yellow because the chain is degraded'."""
    from datetime import timedelta

    _drill_state["active_until"] = datetime.now(UTC) + timedelta(seconds=duration)
    _drill_state["pearl_id"] = pearl_id
    return {
        "drill": "radio-fade",
        "pearl_id": pearl_id,
        "duration_s": duration,
        "active_until": _drill_state["active_until"].isoformat(),
    }


@router.post("/drill/clear")
async def drill_clear() -> dict:
    _drill_state["active_until"] = None
    return {"drill": "cleared"}


def _apply_drill(tower: dict) -> dict:
    """If a drill is active and targets one of this tower's pearls, override
    its score/status to 'bad' so the Loom shows a live degradation."""
    if _drill_state["active_until"] is None:
        return tower
    if datetime.now(UTC) > _drill_state["active_until"]:
        return tower
    if tower.get("tower_id") != "killdeer":
        return tower
    target = _drill_state["pearl_id"]
    pearls = tower.get("pearls", [])
    any_bad = False
    for p in pearls:
        if p.get("pearl_id") == target:
            p["score"] = 18
            p["status"] = "bad"
            any_bad = True
    # Upstream header reflects degraded chain — warn (yellow) per spec
    if any_bad and tower.get("header_status") == "good":
        tower["header_status"] = "warn"
    return tower


@router.get("/grid")
async def collimated_grid(include_sim: bool = Query(True)) -> dict:
    """Collimated tower grid: 1 real + 2 SIM (when include_sim=true).
    Returns the structure the frontend collimated-grid renders."""
    killdeer = await killdeer_pearls()
    killdeer = _apply_drill(killdeer)
    towers = [killdeer]
    if include_sim:
        towers.append(_build_sim_tower("Eddy County", "degraded"))
        towers.append(_build_sim_tower("Culberson", "critical"))
    return {
        "towers": towers,
        "generated_at": datetime.now(UTC).isoformat(),
        "drill_active": _drill_state["active_until"] is not None and datetime.now(UTC) <= _drill_state["active_until"],
    }
