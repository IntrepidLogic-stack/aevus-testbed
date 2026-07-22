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

import structlog
from fastapi import APIRouter, HTTPException

# Service layer (M3): models + topology data, and the flow/process simulation.
# The underscore names are intentionally imported so existing callers that reach
# through this module (e.g. ai._build_twin_context -> twin_mod._derive_flow) and
# test patches keep working unchanged.
from src.services.twin_sim import (
    _derive_flow,
    _opcua_compressor_readings,  # noqa: F401 — re-exported: tests reach it via src.api.twin
    _process_snapshot,
)
from src.services.twin_topology import (
    _FACILITY_ALIASES,
    _TOPOLOGY,
    FlowFrame,
    ProcessSnapshot,
    TwinTopology,
)

router = APIRouter(prefix="/twin", tags=["twin"])
log = structlog.get_logger().bind(component="twin_api")

# Facilities permitted to serve the SIMULATED /process strip. This is the public
# Killdeer demo. A real (non-demo) facility must drive the process strip from live
# RTU telemetry — never from _process_snapshot — so /process returns 404 for it.
# Keeping this an explicit allowlist (not "any known facility") guarantees that
# onboarding a real site can never accidentally leak simulated data as telemetry.
_DEMO_FACILITIES = {"killdeer", "killdeer-bluejay-1", "bluejay-1"}


def _resolve_facility(facility_id: str) -> TwinTopology:
    if facility_id not in _FACILITY_ALIASES:
        raise HTTPException(status_code=404, detail=f"Unknown facility '{facility_id}'")
    return _TOPOLOGY


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


@router.get("/facility/{facility_id}/process", response_model=ProcessSnapshot)
async def get_process(facility_id: str) -> ProcessSnapshot:
    """Live process-strip snapshot for the demo facility (SIMULATED, demo-only).

    Poll this from the Maps page to drive the per-stage engineering readings.
    Facility-gated to the Killdeer demo; never serves real customer telemetry."""
    if facility_id not in _DEMO_FACILITIES:
        # Real / non-demo facility: the simulated strip must not be served. The
        # process strip for a live site is driven from RTU telemetry, not here.
        raise HTTPException(
            status_code=404,
            detail=f"Process strip is simulated demo-only; not served for facility '{facility_id}'",
        )
    topo = _resolve_facility(facility_id)
    return _process_snapshot(topo)
