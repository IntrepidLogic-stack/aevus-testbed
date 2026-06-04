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
    frame={"center": [-95.86769, 29.33956], "zoom": 20.35, "pitch": 55, "bearing": -20},
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
