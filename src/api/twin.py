"""Digital-twin binding contract — facility topology + per-segment flow.

This is the seam (B1 of the Digital Twin Architecture Plan) that decouples the
twin's three layers:

  * BODY (geometry)        — the frontend renders nodes/edges from `topology`.
  * NERVOUS SYSTEM (graph) — `topology` = nodes (equipment) + edges (pipe segments),
                             each with a stable id; geometry binds to it by id.
  * HEARTBEAT (telemetry)  — `flow` = per-segment {flow, dir, status} derived from
                             live asset state, pushed/polled to drive pipe color+speed.

Trade-secret guard (IL): only NORMALIZED flow (0..1) + a coarse status leave the
server. Raw process values, pearl_score weights, and normalization curves stay
server-side. The client stays "dumb" — it just paints what it's told.

IL-9000: read-only. Nothing here writes setpoints or control back to a device.

Endpoints (registered under /api/v1 by main.py):
  GET /api/v1/twin/facility/{facility_id}/topology  -> TwinTopology
  GET /api/v1/twin/facility/{facility_id}/flow       -> FlowFrame (poll; WS later)
"""

from __future__ import annotations

import math
import time
from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/twin", tags=["twin"])
log = structlog.get_logger().bind(component="twin_api")


# ── Models ──────────────────────────────────────────────────────────────────
class TwinModelRef(BaseModel):
    """How the frontend should render this node. Procedural now; glTF later
    (geometry can be swapped without touching the data layer — bind by id)."""

    kind: Literal["procedural", "gltf"] = "procedural"
    ref: str


class TwinNode(BaseModel):
    """A piece of equipment (graph node). `asset_id` binds it to the live registry."""

    id: str
    type: str
    name: str
    lnglat: tuple[float, float]
    asset_id: str | None = None
    model: TwinModelRef


class TwinEdge(BaseModel):
    """A pipe segment (graph edge), product-typed and flow-ready.

    `src` serializes as "from" (reserved word in JS/Python) so the wire contract
    reads {from, to}. `asset_id` binds the segment's flow to a telemetry source."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    src: str = Field(serialization_alias="from")
    to: str
    product: Literal["oil", "gas", "water", "chemical"]
    diameter_in: float | None = None
    rack_h_m: float = 2.2
    asset_id: str | None = None


class TwinTopology(BaseModel):
    facility_id: str
    name: str
    origin: tuple[float, float]
    frame: dict
    nodes: list[TwinNode]
    edges: list[TwinEdge]


class FlowSegment(BaseModel):
    """Live state of one pipe segment. `flow` is NORMALIZED 0..1 (raw rate hidden)."""

    id: str
    product: str
    flow: float
    dir: int  # +1 forward, -1 reverse, 0 stopped
    status: Literal["good", "warn", "bad", "unknown"]


class FlowFrame(BaseModel):
    facility_id: str
    segments: list[FlowSegment]


# ── Killdeer / BlueJay #1 topology (server-authored; later -> Postgres) ──────
# Coordinates mirror the live 3D facility so geometry and graph agree by id.
_FACILITY_ID = "killdeer-bluejay-1"
_FACILITY_ALIASES = {"killdeer", "killdeer-bluejay-1", "bluejay-1"}

_TOPOLOGY = TwinTopology(
    facility_id=_FACILITY_ID,
    name="Killdeer Field — BlueJay Unit #1",
    origin=(-95.8685, 29.3396),
    frame={"center": [-95.86769, 29.33956], "zoom": 20.0, "pitch": 55, "bearing": -20},
    nodes=[
        TwinNode(
            id="WH",
            type="wellhead",
            name="Wellhead — BlueJay #1",
            lnglat=(-95.86790, 29.33982),
            model=TwinModelRef(ref="wellhead"),
        ),
        TwinNode(
            id="CHE",
            type="chemtote",
            name="Chemical Injection",
            lnglat=(-95.86800, 29.33978),
            model=TwinModelRef(ref="chemtote"),
        ),
        TwinNode(
            id="SEP",
            type="separator",
            name="2-Phase Separator",
            lnglat=(-95.86790, 29.33965),
            asset_id="RTU-01",
            model=TwinModelRef(ref="separator"),
        ),
        TwinNode(
            id="CMP",
            type="compressor",
            name="Gas-Lift Compressor",
            lnglat=(-95.86815, 29.33968),
            asset_id="RTU-01",
            model=TwinModelRef(ref="compressor"),
        ),
        TwinNode(
            id="OT1",
            type="oiltank",
            name="Stock Tank #1",
            lnglat=(-95.86755, 29.33967),
            model=TwinModelRef(ref="oiltank"),
        ),
        TwinNode(
            id="OT2",
            type="oiltank",
            name="Stock Tank #2",
            lnglat=(-95.86755, 29.33960),
            model=TwinModelRef(ref="oiltank"),
        ),
        TwinNode(
            id="PWT",
            type="watertank",
            name="Produced Water Tank",
            lnglat=(-95.86742, 29.33965),
            model=TwinModelRef(ref="watertank"),
        ),
        TwinNode(
            id="EFM",
            type="efm",
            name="EFM / Custody Meter",
            lnglat=(-95.86735, 29.33948),
            asset_id="RTU-01",
            model=TwinModelRef(ref="efm"),
        ),
        TwinNode(
            id="FLR", type="flare", name="Flare Stack", lnglat=(-95.86790, 29.33932), model=TwinModelRef(ref="flare")
        ),
        TwinNode(
            id="TWR",
            type="tower",
            name="Radio Tower",
            lnglat=(-95.86735, 29.33992),
            asset_id="RAD-01",
            model=TwinModelRef(ref="tower"),
        ),
        # ── New process/support assets (registered 2026-06-04). Positions are
        # PROVISIONAL on the procedural twin and will be reconciled with the
        # Spline scene layout when it lands. Bound to RTU-01 for live status.
        TwinNode(
            id="HTR",
            type="heater",
            name="Line Heater / Scrubber",
            lnglat=(-95.86808, 29.33958),
            asset_id="RTU-01",
            model=TwinModelRef(ref="heater"),
        ),
        TwinNode(
            id="RTU",
            type="shelter",
            name="PLC Shelter",
            lnglat=(-95.86772, 29.33948),
            asset_id="RTU-01",
            model=TwinModelRef(ref="shelter"),
        ),
        TwinNode(
            id="PWR",
            type="power",
            name="Power System",
            lnglat=(-95.86756, 29.33980),
            asset_id="RTU-01",
            model=TwinModelRef(ref="power"),
        ),
    ],
    edges=[
        TwinEdge(id="P1", src="WH", to="SEP", product="gas", diameter_in=3, rack_h_m=2.4, asset_id="RTU-01"),
        TwinEdge(id="P2", src="CHE", to="WH", product="chemical", diameter_in=1, rack_h_m=1.8),
        TwinEdge(id="P3", src="SEP", to="CMP", product="gas", diameter_in=3, rack_h_m=2.6, asset_id="RTU-01"),
        TwinEdge(id="P4", src="SEP", to="OT1", product="oil", diameter_in=4, rack_h_m=2.0, asset_id="RTU-01"),
        TwinEdge(id="P5", src="SEP", to="PWT", product="water", diameter_in=3, rack_h_m=2.2, asset_id="RTU-01"),
        TwinEdge(id="P6", src="CMP", to="FLR", product="gas", diameter_in=2, rack_h_m=2.8, asset_id="RTU-01"),
        TwinEdge(id="P7", src="CMP", to="EFM", product="gas", diameter_in=3, rack_h_m=2.5, asset_id="RTU-01"),
    ],
)

# Per-product baseline normalized flow (design-relative). Until the SCADAPack 470
# process point-map is finished, segment flow is modulated by the bound asset's
# health/status — honest "asset-level" data, not raw per-segment process flow.
_BASE_FLOW = {"gas": 0.82, "oil": 0.60, "water": 0.50, "chemical": 0.30}
_STATUS_MULT = {"good": 1.0, "warn": 0.6, "bad": 0.15, "unknown": 0.55, "offline": 0.0}


def _resolve_facility(facility_id: str) -> TwinTopology:
    if facility_id not in _FACILITY_ALIASES:
        raise HTTPException(status_code=404, detail=f"Unknown facility '{facility_id}'")
    return _TOPOLOGY


def _derive_flow(topo: TwinTopology) -> list[FlowSegment]:
    """Map live asset status onto each segment -> normalized flow + status.

    Reads the asset registry (same source as /api/v1/assets) and modulates the
    per-product baseline by the bound asset's status. Only normalized values
    leave here — no raw process readings, no scoring internals."""
    from src.main import app_state  # lazy import (avoids circular import)

    by_id = {}
    try:
        for a in app_state.db.list_assets():
            by_id[a.id] = a
    except Exception as exc:  # registry unavailable -> baseline-only flow
        log.warning("twin_flow_registry_unavailable", error=str(exc))

    segs: list[FlowSegment] = []
    for e in topo.edges:
        base = _BASE_FLOW.get(e.product, 0.5)
        status = "unknown"
        mult = _STATUS_MULT["unknown"]
        asset = by_id.get(e.asset_id) if e.asset_id else None
        if asset is not None:
            raw = getattr(asset, "status", "unknown")
            status = raw if raw in ("good", "warn", "bad") else "unknown"
            mult = _STATUS_MULT.get(raw, 0.55)
        flow = round(max(0.0, min(1.0, base * mult)), 3)
        segs.append(FlowSegment(id=e.id, product=e.product, flow=flow, dir=1 if flow > 0 else 0, status=status))
    return segs


# ── Endpoints ────────────────────────────────────────────────────────────────
@router.get("/facility/{facility_id}/topology", response_model=TwinTopology)
async def get_topology(facility_id: str) -> TwinTopology:
    """Static-ish facility graph: nodes (equipment) + edges (pipe segments).

    The frontend loads this once and builds geometry indexed by id, then listens
    for flow updates — geometry and data evolve independently."""
    return _resolve_facility(facility_id)


@router.get("/facility/{facility_id}/flow", response_model=FlowFrame)
async def get_flow(facility_id: str) -> FlowFrame:
    """Current per-segment flow (normalized 0..1 + status), derived from live
    asset state. Poll this (or, later, subscribe via WS) to drive pipe color/speed."""
    topo = _resolve_facility(facility_id)
    return FlowFrame(facility_id=topo.facility_id, segments=_derive_flow(topo))


# ── Process snapshot (demo facility process strip) ───────────────────────────
#
# Drives the live process-flow strip on the Maps page: per-stage engineering
# readings (TBG/CSG, separator P/level, compressor SUCT/DISCH/RPM, tank levels,
# custody meter rate/total) plus the sales summary (oil BOPD, gas MCFD).
#
# ⚠️ SIMULATED DEMO DATA ONLY. This endpoint serves a physically-consistent
# model of the *public Killdeer demo* facility — it is gated to the demo
# facility aliases and must never be wired to real customer process telemetry.
# Real raw process values + pearl_score internals stay server-side (IL
# trade-secret guard); the /flow endpoint (normalized 0..1) remains the path
# for any non-demo facility.
#
# The numbers are internally coherent (oil/water cut tie to BOPD/BWPD, custody
# total is monotonic, gathering pressures are low-pressure realistic) and drift
# on a slow load cycle so each poll shows gentle live movement.


class ProcessReading(BaseModel):
    """One engineering reading within a stage."""

    label: str
    value: float
    unit: str
    status: Literal["good", "warn", "bad", "unknown"] = "good"


class ProcessStage(BaseModel):
    """One process stage (wellhead, separator, …) with its readings."""

    id: str
    name: str
    status: Literal["good", "warn", "bad", "unknown"] = "good"
    readings: list[ProcessReading]


class ProcessSnapshot(BaseModel):
    facility_id: str
    ts: int
    stages: list[ProcessStage]
    sales: dict


# Fixed reference epoch (2024-05-29) so the custody total is monotonic and the
# load-cycle phase is stable across restarts.
_PROC_EPOCH = 1_716_940_800


def _proc_drift(t: float) -> float:
    """Smooth -1..1 load oscillation (≈6 min primary + ≈2.3 min secondary)."""
    primary = math.sin((t / 360.0) * 2 * math.pi)
    secondary = math.sin((t / 137.0 + 0.3) * 2 * math.pi)
    return max(-1.0, min(1.0, 0.7 * primary + 0.3 * secondary))


def _process_snapshot(topo: TwinTopology) -> ProcessSnapshot:
    """Physically-consistent simulated wellsite process snapshot (demo only)."""
    t = time.time()
    d = _proc_drift(t)

    def v(base: float, amp: float) -> float:
        return base + amp * d

    # ── coherent gas-lift wellsite state ──────────────────────────────────
    tubing = v(285.0, 12.0)
    casing = v(325.0, 14.0)
    choke = v(65.0, 3.0)
    sep_p = v(125.0, 6.0)
    sep_l = v(55.0, 5.0)
    sep_dp = v(4.5, 0.8)
    suction = v(28.0, 3.0)
    discharge = v(89.0, 6.0)
    rpm = v(1180.0, 22.0)
    gas_t = v(140.0, 7.0)
    vib = v(2.8, 0.5)
    oil_lvl = v(72.0, 6.0)
    wat_lvl = v(48.0, 5.0)
    mcfd = v(3.9, 0.35)
    dp = v(53.7, 4.0)
    static_p = v(497.0, 8.0)
    oil_bopd = v(45.0, 4.0)
    wcut = v(36.0, 2.0)  # water cut %
    # custody total creeps up monotonically with the gas rate
    accum = 125944.0 + max(0.0, (t - _PROC_EPOCH)) / 86400.0 * 3.9
    # water rate ties to oil rate via the water cut (mass balance)
    bwpd = oil_bopd * wcut / max(1.0, (100.0 - wcut))

    def rd(label: str, val: float, unit: str, status: str = "good") -> ProcessReading:
        return ProcessReading(label=label, value=round(val, 1), unit=unit, status=status)

    stages = [
        ProcessStage(
            id="wellhead",
            name="Wellhead",
            readings=[rd("TBG", tubing, "PSI"), rd("CSG", casing, "PSI"), rd("CHOKE", choke, "%")],
        ),
        ProcessStage(
            id="separator",
            name="Separator",
            readings=[rd("PRESS", sep_p, "PSI"), rd("LEVEL", sep_l, "%"), rd("ΔP", sep_dp, "PSI")],
        ),
        ProcessStage(
            id="compressor",
            name="Compressor",
            readings=[
                rd("SUCT", suction, "PSI"),
                rd("DISCH", discharge, "PSI"),
                rd("RPM", rpm, ""),
                rd("GAS", gas_t, "°F"),
                rd("VIB", vib, "mm/s"),
            ],
        ),
        ProcessStage(
            id="tankfarm",
            name="Tank Farm",
            readings=[rd("OIL", oil_lvl, "in"), rd("WATER", wat_lvl, "in"), rd("W.CUT", wcut, "%")],
        ),
        ProcessStage(
            id="metering",
            name="Metering",
            readings=[
                rd("RATE", mcfd, "MCFD"),
                rd("TOTAL", accum, "MCF"),
                rd("DP", dp, "inH₂O"),
                rd("STATIC", static_p, "PSIG"),
            ],
        ),
    ]
    sales = {
        "oil_bopd": round(oil_bopd, 1),
        "gas_mcfd": round(mcfd, 1),
        "water_bwpd": round(bwpd, 1),
    }
    return ProcessSnapshot(facility_id=topo.facility_id, ts=int(t), stages=stages, sales=sales)


@router.get("/facility/{facility_id}/process", response_model=ProcessSnapshot)
async def get_process(facility_id: str) -> ProcessSnapshot:
    """Live process-strip snapshot for the demo facility (SIMULATED, demo-only).

    Poll this from the Maps page to drive the per-stage engineering readings.
    Facility-gated to the Killdeer demo; never serves real customer telemetry."""
    topo = _resolve_facility(facility_id)
    return _process_snapshot(topo)
