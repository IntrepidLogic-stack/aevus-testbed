"""Digital-twin topology contract + facility data (extracted from api/twin.py, M3).

The Pydantic wire models and the server-authored Killdeer/BlueJay #1 topology
literal. Routers and the sim import from here; this module has NO FastAPI or
runtime-state dependencies. Trade-secret guard and IL-9000 notes live with the
router (src/api/twin.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
                -95.86718,
                29.33958,
            ),  # pulled further SE onto a clear downwind sub-grid — walking room from the water skids, away from the solar array + Ask-box UI
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
            lnglat=(
                -95.86726,
                29.33977,
            ),  # pulled N + E of the SWD pump for walking room (downstream disposal measurement)
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
        # VRU RECOVERY: the primary path RECOMPRESSES recovered vapor back to the
        # compressor suction (sold, not burned). The combustor (V2) is the excess /
        # upset path only. This is how a real VRU pays for itself.
        TwinEdge(id="VRe", src="VRU", to="CMP", product="gas", diameter_in=2, rack_h_m=2.0, asset_id="RTU-01"),
        TwinEdge(id="V2", src="VRU", to="CMB", product="gas", diameter_in=2, rack_h_m=1.8),
        # TEG regenerator still-vent + flash gas -> vapor recovery (NOT atmosphere).
        # The dehy reboiler still column and the glycol flash tank are two of the
        # three regulated emission sources on a gas pad (NSPS OOOOb); route them to
        # the VRU so they share the combustor with the tank vapors.
        TwinEdge(id="V3", src="DEHY", to="VRU", product="gas", diameter_in=2, rack_h_m=1.7),
        # Compressor rod-packing / seal vent -> vapor recovery (the 3rd regulated
        # emission source after tank vapors + dehy still-vent; NSPS OOOOb).
        TwinEdge(id="RP", src="CMP", to="VRU", product="gas", diameter_in=1, rack_h_m=1.9, asset_id="RTU-01"),
        # Produced water -> saltwater disposal pump -> disposal METER (volume custody).
        TwinEdge(id="W1", src="PWT", to="SWD", product="water", diameter_in=3, rack_h_m=1.8, asset_id="RTU-01"),
        TwinEdge(id="W2", src="SWD", to="WM", product="water", diameter_in=3, rack_h_m=1.6, asset_id="RTU-01"),
        # Fuel gas: tapped off compressor discharge, conditioned, sent to the heater
        # (and the TEG reboiler + pneumatics). Every gas pad burns its own gas.
        TwinEdge(id="F1", src="CMP", to="FGS", product="gas", diameter_in=2, rack_h_m=1.8, asset_id="RTU-01"),
        TwinEdge(id="F2", src="FGS", to="HTR", product="gas", diameter_in=1, rack_h_m=1.6, asset_id="RTU-01"),
        # Fuel gas also fires the TEG reboiler (the other big on-site fuel user).
        TwinEdge(id="F3", src="FGS", to="DEHY", product="gas", diameter_in=1, rack_h_m=1.5, asset_id="RTU-01"),
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
        # RELIEF HEADER — the vessel PSVs (separator, TEG dehy) tie into the relief
        # header to the flare KO drum, alongside the compressor relief (P6). This is
        # the over-pressure protection path every vessel needs.
        TwinEdge(id="R1", src="SEP", to="FLR", product="gas", diameter_in=3, rack_h_m=3.0, inline="flare_valve"),
        TwinEdge(id="R2", src="DEHY", to="FLR", product="gas", diameter_in=2, rack_h_m=3.0, inline="flare_valve"),
        # Sales pipeline backbone: custody-sold gas leaves the wellsite meter and
        # runs to the downstream metering station (Phase 3 multi-station).
        TwinEdge(id="BB1", src="EFM", to="M2-KO", product="gas", diameter_in=6, rack_h_m=2.4),
        TwinEdge(id="BB2", src="M2-KO", to="M2-EFM", product="gas", diameter_in=6, rack_h_m=2.4),
    ],
)
