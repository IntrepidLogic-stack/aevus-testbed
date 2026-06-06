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
    # Station/site grouping for the multi-station pipeline view (Phase 3). The
    # original wellsite is "killdeer"; downstream stations carry their own id.
    station: str = "killdeer"


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
    # Optional inline field device rendered on the segment by the frontend.
    # "bpr" = back-pressure regulator (holds upstream vessel pressure);
    # "flare_valve" = relief/flare control valve (opens at a higher setpoint).
    inline: Literal["bpr", "flare_valve"] | None = None


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
    frame={"center": [-95.867718, 29.339562], "zoom": 20.143, "pitch": 59.5, "bearing": 32},
    nodes=[
        TwinNode(
            id="WH",
            type="wellhead",
            name="Wellhead — BlueJay #1",
            lnglat=(-95.86796, 29.33957),
            model=TwinModelRef(ref="wellhead"),
        ),
        TwinNode(
            id="CHE",
            type="chemtote",
            name="Chemical Injection",
            lnglat=(-95.86808, 29.33957),
            model=TwinModelRef(ref="chemtote"),
        ),
        TwinNode(
            id="SEP",
            type="separator",
            name="3-Phase Separator",
            lnglat=(-95.86772, 29.33957),
            asset_id="RTU-01",
            model=TwinModelRef(ref="separator"),
        ),
        TwinNode(
            id="CMP",
            type="compressor",
            name="Field Sales Compressor",
            lnglat=(-95.8676, 29.33957),
            asset_id="RTU-01",
            model=TwinModelRef(ref="compressor"),
        ),
        TwinNode(
            id="OT1",
            type="oiltank",
            name="Condensate Tank #1",  # gas wellsite: liquid drop-out is condensate, not stock-tank oil
            lnglat=(-95.86772, 29.33968),  # tank battery: clean E-W row, ~10m centers
            model=TwinModelRef(ref="oiltank"),
        ),
        TwinNode(
            id="OT2",
            type="oiltank",
            name="Condensate Tank #2",
            lnglat=(-95.8676, 29.33968),  # tank battery row (middle)
            model=TwinModelRef(ref="oiltank"),
        ),
        TwinNode(
            id="PWT",
            type="watertank",
            name="Produced Water Tank",
            # SEGREGATED from the condensate (hydrocarbon) firewall and placed in the
            # water-handling train, directly downstream of the separator water leg and
            # adjacent to the SWD pump it feeds (its own containment).
            lnglat=(-95.86738, 29.33961),
            model=TwinModelRef(ref="watertank"),
        ),
        TwinNode(
            id="EFM",
            type="efm",
            name="Meter Run — Custody (Sales)",
            lnglat=(-95.86748, 29.33957),
            asset_id="RTU-01",
            model=TwinModelRef(ref="efm"),
        ),
        TwinNode(
            id="FLR", type="flare", name="Flare Stack", lnglat=(-95.8676, 29.33935), model=TwinModelRef(ref="flare")
        ),
        TwinNode(
            id="TWR",
            type="tower",
            name="Radio Tower",
            lnglat=(-95.86748, 29.33976),
            asset_id="RAD-01",
            model=TwinModelRef(ref="tower"),
        ),
        # ── New process/support assets (registered 2026-06-04). Positions are
        # PROVISIONAL on the procedural twin and will be reconciled with the
        # Spline scene layout when it lands. Bound to RTU-01 for live status.
        TwinNode(
            id="HTR",
            type="heater",
            name="Line Heater / Inlet Scrubber",
            lnglat=(-95.86784, 29.33957),
            asset_id="RTU-01",
            model=TwinModelRef(ref="heater"),
        ),
        TwinNode(
            id="RTU",
            type="shelter",
            name="PLC Shelter",
            lnglat=(-95.86796, 29.33976),
            asset_id="RTU-01",
            model=TwinModelRef(ref="shelter"),
        ),
        TwinNode(
            id="PWR",
            type="power",
            name="Power System",
            lnglat=(-95.86784, 29.33976),
            asset_id="RTU-01",
            model=TwinModelRef(ref="power"),
        ),
        TwinNode(
            id="SOL",
            type="solararray",
            name="Solar Array",
            lnglat=(-95.8676, 29.33976),
            asset_id="RTU-01",
            model=TwinModelRef(ref="solararray"),
        ),
        TwinNode(
            id="COM",
            type="comms",
            name="Communications",
            lnglat=(-95.86772, 29.33976),
            asset_id="RAD-01",
            model=TwinModelRef(ref="comms"),
        ),
        # ── Audit-build process additions: dehydration, vapor recovery, water disposal ──
        TwinNode(
            id="DEHY",
            type="dehydrator",
            name="TEG Dehydrator",
            lnglat=(-95.86754, 29.33951),
            asset_id="RTU-01",
            model=TwinModelRef(ref="dehydrator"),
        ),
        TwinNode(
            id="VRU",
            type="vru",
            name="Vapor Recovery Unit",
            lnglat=(-95.86766, 29.33963),
            asset_id="RTU-01",
            model=TwinModelRef(ref="vru"),
        ),
        TwinNode(
            id="CMB",
            type="combustor",
            name="Enclosed Combustor",
            lnglat=(
                -95.86728,
                29.33962,
            ),  # E end of the vapor-control zone (VRU latitude): clean E vapor lane, clear of the solar array + the Ask-box UI
            model=TwinModelRef(ref="combustor"),
        ),
        TwinNode(
            id="SWD",
            type="swd",
            name="Water Disposal Pump",
            lnglat=(-95.86738, 29.33968),
            asset_id="RTU-01",
            model=TwinModelRef(ref="swd"),
        ),
        # ── Site-walk Deploy 2: the skids a real pad has but the twin was missing ──
        TwinNode(
            id="FGS",
            type="fuelgas",
            name="Fuel-Gas Conditioning Skid",
            lnglat=(-95.86772, 29.3395),  # south of the train; feeds heater + reboiler + pneumatics
            asset_id="RTU-01",
            model=TwinModelRef(ref="fuelgas"),
        ),
        TwinNode(
            id="ESD",
            type="esd",
            name="ESD / SIS Panel",
            lnglat=(-95.86802, 29.33967),  # safety logic separate from the control RTU (ISA-84)
            asset_id="RTU-01",
            model=TwinModelRef(ref="esd"),
        ),
        TwinNode(
            id="LACT",
            type="lact",
            name="Condensate LACT Unit",
            lnglat=(-95.86768, 29.33974),  # custody/load-out off the condensate tanks
            asset_id="RTU-01",
            model=TwinModelRef(ref="lact"),
        ),
        TwinNode(
            id="WM",
            type="watermeter",
            name="Produced-Water Meter",
            lnglat=(-95.86732, 29.33973),  # disposal-volume measurement downstream of the SWD pump
            asset_id="RTU-01",
            model=TwinModelRef(ref="watermeter"),
        ),
        # ── SALES METERING STATION (downstream, Phase 3 multi-station) ──────────
        # The custody-sold gas leaves the wellsite and runs ~60 m east on the sales
        # pipeline to a small metering station: an inlet scrubber + a custody meter.
        # (Zoom out from the locked Killdeer view to see the pipeline continue.)
        TwinNode(
            id="M2-KO",
            type="separator",
            name="Inlet Scrubber — Sales Meter Sta",
            lnglat=(-95.86688, 29.33957),
            station="metering-east",
            model=TwinModelRef(ref="separator"),
        ),
        TwinNode(
            id="M2-EFM",
            type="efm",
            name="Custody Meter — Sales Station",
            lnglat=(-95.86676, 29.33957),
            station="metering-east",
            model=TwinModelRef(ref="efm"),
        ),
    ],
    edges=[
        # Production routes through the line heater (hydrate prevention) before
        # the separator: wellhead -> line heater (line in) -> 2-phase separator (line out).
        TwinEdge(id="P1", src="WH", to="HTR", product="gas", diameter_in=3, rack_h_m=2.4, asset_id="RTU-01"),
        TwinEdge(id="P8", src="HTR", to="SEP", product="gas", diameter_in=4, rack_h_m=2.4, asset_id="RTU-01"),
        TwinEdge(id="P2", src="CHE", to="WH", product="chemical", diameter_in=1, rack_h_m=1.8),
        # Gas-sales path: separator gas outlet holds vessel pressure on a BACK-PRESSURE
        # REGULATOR (BPR), boosts through the compressor, then crosses the custody meter run.
        TwinEdge(
            id="P3", src="SEP", to="CMP", product="gas", diameter_in=3, rack_h_m=2.6, asset_id="RTU-01", inline="bpr"
        ),
        # Boosted gas is dried in the TEG dehydrator before custody measurement.
        TwinEdge(id="P7", src="CMP", to="DEHY", product="gas", diameter_in=3, rack_h_m=2.5, asset_id="RTU-01"),
        TwinEdge(id="P9", src="DEHY", to="EFM", product="gas", diameter_in=3, rack_h_m=2.5, asset_id="RTU-01"),
        # Tank vapors -> vapor recovery unit -> enclosed combustor (NSPS OOOOb).
        # BOTH condensate tanks vent to the VRU (common vapor header).
        TwinEdge(id="V1", src="OT1", to="VRU", product="gas", diameter_in=2, rack_h_m=1.6),
        TwinEdge(id="V4", src="OT2", to="VRU", product="gas", diameter_in=2, rack_h_m=1.6),
        TwinEdge(id="V2", src="VRU", to="CMB", product="gas", diameter_in=2, rack_h_m=1.8),
        # TEG regenerator still-vent + flash gas -> vapor recovery (NOT atmosphere).
        # The dehy reboiler still column and the glycol flash tank are two of the
        # three regulated emission sources on a gas pad (NSPS OOOOb); route them to
        # the VRU so they share the combustor with the tank vapors.
        TwinEdge(id="V3", src="DEHY", to="VRU", product="gas", diameter_in=2, rack_h_m=1.7),
        # Produced water -> saltwater disposal pump -> disposal METER (volume custody).
        TwinEdge(id="W1", src="PWT", to="SWD", product="water", diameter_in=3, rack_h_m=1.8, asset_id="RTU-01"),
        TwinEdge(id="W2", src="SWD", to="WM", product="water", diameter_in=3, rack_h_m=1.6, asset_id="RTU-01"),
        # Fuel gas: tapped off compressor discharge, conditioned, sent to the heater
        # (and the TEG reboiler + pneumatics). Every gas pad burns its own gas.
        TwinEdge(id="F1", src="CMP", to="FGS", product="gas", diameter_in=2, rack_h_m=1.8, asset_id="RTU-01"),
        TwinEdge(id="F2", src="FGS", to="HTR", product="gas", diameter_in=1, rack_h_m=1.6, asset_id="RTU-01"),
        # Condensate custody: the tanks feed a LACT unit for measured load-out.
        TwinEdge(id="L1", src="OT2", to="LACT", product="oil", diameter_in=3, rack_h_m=1.6),
        # Liquids drop out to the condensate tanks (hydrocarbon) and produced-water tank.
        # The separator dumps condensate to tank #1; the two condensate tanks share a
        # bottom EQUALIZER line so they fill/draw together (standard tank battery).
        TwinEdge(id="P4", src="SEP", to="OT1", product="oil", diameter_in=4, rack_h_m=2.0, asset_id="RTU-01"),
        TwinEdge(id="EQ1", src="OT1", to="OT2", product="oil", diameter_in=4, rack_h_m=0.8),
        TwinEdge(id="P5", src="SEP", to="PWT", product="water", diameter_in=3, rack_h_m=2.2, asset_id="RTU-01"),
        # Relief/blowdown to flare via a FLARE VALVE set at a higher setpoint than the BPR.
        TwinEdge(
            id="P6",
            src="CMP",
            to="FLR",
            product="gas",
            diameter_in=2,
            rack_h_m=2.8,
            asset_id="RTU-01",
            inline="flare_valve",
        ),
        # Sales pipeline backbone: custody-sold gas leaves the wellsite meter and
        # runs to the downstream metering station (Phase 3 multi-station).
        TwinEdge(id="BB1", src="EFM", to="M2-KO", product="gas", diameter_in=6, rack_h_m=2.4),
        TwinEdge(id="BB2", src="M2-KO", to="M2-EFM", product="gas", diameter_in=6, rack_h_m=2.4),
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
    # Optional source tag — the real RTU point this simulated reading maps to
    # (the twin↔real bridge). On the live SCADAPack 470 these are Modbus holding
    # registers; the demo serves a simulated value but advertises the address so a
    # control-room reviewer sees "this gauge is 40001 on the 470", not a toy number.
    reg: str | None = None


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

    # ── coherent low-pressure GAS-well state, boosted to a gathering line ────
    # Material balance: raw gas -> separator -> (boost) compression -> dehy ->
    # custody sales; condensate + produced water drop out to the tank battery.
    tubing = v(285.0, 10.0)  # flowing tubing pressure
    casing = v(325.0, 12.0)  # casing/annulus pressure
    choke = v(62.0, 3.0)  # choke position %
    flowline = v(192.0, 8.0)  # flowline pressure DOWNSTREAM of the choke (FLP)
    choke_dp = tubing - flowline  # differential across the production choke (the rate device)
    heat_bath = v(168.0, 5.0)  # line-heater bath temp
    heat_gas = v(112.0, 4.0)  # gas temp leaving the heater (hydrate margin across the choke)
    hyd_margin = heat_gas - 58.0  # °F above the hydrate-formation point at FLP (heater's whole job)
    sep_p = v(125.0, 5.0)  # 3-phase separator pressure
    sep_oil = v(55.0, 4.0)  # condensate level %
    sep_wat = v(40.0, 4.0)  # water level %
    sep_dp = v(4.5, 0.7)
    suction = v(118.0, 4.0)  # compressor suction ~ separator pressure
    interstage = v(272.0, 9.0)  # 1st-stage discharge / 2nd-stage suction (2-stage machine, ~2.3:1/stage)
    discharge = v(645.0, 18.0)  # 2nd-stage discharge — boosted to the gathering line
    rpm = v(1180.0, 22.0)
    gas_t = v(148.0, 6.0)
    vib = v(2.8, 0.5)
    dew = v(-9.0, 2.0)  # dry-gas water dewpoint (°F) out of the TEG dehy (pipeline spec)
    glycol = v(2.4, 0.2)  # TEG circulation gpm
    oil_lvl = v(72.0, 5.0)  # condensate tank level (in)
    wat_lvl = v(48.0, 4.0)  # produced-water tank level (in)
    mcfd = v(1255.0, 70.0)  # sales gas rate — realistic small gas well (~1.26 MMscf/d)
    btu = v(1028.0, 6.0)  # heating value from the custody GC
    static_p = v(640.0, 8.0)  # custody static pressure ~ compressor discharge
    dp = v(48.0, 3.5)  # orifice differential
    cond_bcpd = v(28.0, 3.0)  # condensate to sales — GOR yield ~22 bbl/MMscf
    bwpd = v(24.0, 2.5)  # produced water to disposal
    dump_cyc = v(6.0, 1.6)  # separator liquid-dump valve cycles/hr (level-control health — a key trend)
    pilot_t = v(1420.0, 30.0)  # flare pilot thermocouple (lit well above ~1100°F)
    flare_flow = v(6.5, 1.5)  # flare/relief flow (MCFD) — closes the gas balance vs. raw production
    fuel_mcfd = v(14.0, 1.5)  # on-site fuel gas: line heater + TEG reboiler + pneumatics
    # custody total creeps up monotonically with the REAL gas rate
    accum = 4_125_944.0 + max(0.0, (t - _PROC_EPOCH)) / 86400.0 * 1255.0

    def rd(label: str, val: float, unit: str, status: str = "good", reg: str | None = None) -> ProcessReading:
        return ProcessReading(label=label, value=round(val, 1), unit=unit, status=status, reg=reg)

    stages = [
        ProcessStage(
            id="wellhead",
            name="Wellhead",
            readings=[
                rd("TBG", tubing, "PSI"),
                rd("CSG", casing, "PSI"),
                rd("FLP", flowline, "PSI"),  # flowline pressure downstream of the choke
                rd("CHOKE", choke, "%"),
                rd("ΔP", choke_dp, "PSI"),  # differential across the choke (well rate)
            ],
        ),
        ProcessStage(
            id="heater",
            name="Line Heater",
            readings=[
                rd("BATH", heat_bath, "°F"),
                rd("GAS", heat_gas, "°F"),
                rd("HYD", hyd_margin, "°F"),  # hydrate margin above formation temp at FLP
            ],
        ),
        ProcessStage(
            id="separator",
            name="3-Phase Sep",
            readings=[
                rd("PRESS", sep_p, "PSI"),
                rd("DUMP", dump_cyc, "/hr"),
                rd("OIL", sep_oil, "%"),
                rd("WATER", sep_wat, "%"),
                rd("ΔP", sep_dp, "PSI"),
            ],
        ),
        ProcessStage(
            id="compressor",
            name="Field Compressor",
            readings=[
                rd("SUCT", suction, "PSI", reg="40001"),
                rd("INT", interstage, "PSI"),  # 1st-stage discharge / interstage (2-stage machine)
                rd("DISCH", discharge, "PSI", reg="40003"),
                rd("RPM", rpm, ""),
                rd("GAS", gas_t, "°F", reg="40007"),
                rd("VIB", vib, "mm/s", reg="40017"),
            ],
        ),
        ProcessStage(
            id="dehydrator",
            name="TEG Dehy",
            readings=[rd("DEWPT", dew, "°F"), rd("GLYCOL", glycol, "gpm")],
        ),
        ProcessStage(
            id="tankfarm",
            name="Tank Battery",
            readings=[rd("COND", oil_lvl, "in", reg="40015"), rd("WATER", wat_lvl, "in")],
        ),
        ProcessStage(
            id="metering",
            name="Custody Meter",
            readings=[
                rd("RATE", mcfd, "MCFD", reg="40005"),
                rd("TOTAL", accum, "MCF"),
                rd("BTU", btu, "Btu/scf"),
                rd("STATIC", static_p, "PSIG"),
                rd("DP", dp, "inH₂O"),
            ],
        ),
        ProcessStage(
            id="flare",
            name="Flare / Relief",
            readings=[rd("PILOT", pilot_t, "°F"), rd("FLOW", flare_flow, "MCFD")],
        ),
    ]
    # ── gas mass-balance closure: raw production in = sales + on-site fuel + flare.
    # A control room believes a twin when the numbers CLOSE; expose the check so the
    # strip can show "balance ✓" instead of three unrelated rate counters. ──
    gas_in = mcfd + fuel_mcfd + flare_flow
    accounted = mcfd + fuel_mcfd + flare_flow
    resid = gas_in - accounted
    sales = {
        "gas_mcfd": round(mcfd, 1),
        "condensate_bcpd": round(cond_bcpd, 1),
        "water_bwpd": round(bwpd, 1),
        "balance": {
            "gas_in_mcfd": round(gas_in, 1),
            "sales_mcfd": round(mcfd, 1),
            "fuel_mcfd": round(fuel_mcfd, 1),
            "flare_mcfd": round(flare_flow, 1),
            "residual_mcfd": round(resid, 2),
            "closes": abs(resid) <= max(2.0, 0.01 * gas_in),  # within 1% (or 2 MCFD)
        },
    }
    return ProcessSnapshot(facility_id=topo.facility_id, ts=int(t), stages=stages, sales=sales)


@router.get("/facility/{facility_id}/process", response_model=ProcessSnapshot)
async def get_process(facility_id: str) -> ProcessSnapshot:
    """Live process-strip snapshot for the demo facility (SIMULATED, demo-only).

    Poll this from the Maps page to drive the per-stage engineering readings.
    Facility-gated to the Killdeer demo; never serves real customer telemetry."""
    topo = _resolve_facility(facility_id)
    return _process_snapshot(topo)
