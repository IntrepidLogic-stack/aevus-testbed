"""Digital-twin flow derivation + demo process simulation (extracted from api/twin.py, M3).

Pure derivation/simulation: maps live asset state onto normalized segment flow,
and produces the physically-consistent SIMULATED process snapshot for the public
Killdeer demo. The demo-facility gate lives in the router (src/api/twin.py) —
this module must only ever be called for demo facilities.
"""

from __future__ import annotations

import contextlib
import math
import time

import structlog

from src.services.twin_topology import (
    FlowSegment,
    ProcessReading,
    ProcessSnapshot,
    ProcessStage,
    TwinTopology,
)

log = structlog.get_logger().bind(component="twin_sim")

# Per-product baseline normalized flow (design-relative). Until the SCADAPack 470
# process point-map is finished, segment flow is modulated by the bound asset's
# health/status — honest "asset-level" data, not raw per-segment process flow.
_BASE_FLOW = {"gas": 0.82, "oil": 0.60, "water": 0.50, "chemical": 0.30}
_STATUS_MULT = {"good": 1.0, "warn": 0.6, "bad": 0.15, "unknown": 0.55, "offline": 0.0}


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

# Fixed reference epoch (2024-05-29) so the custody total is monotonic and the
# load-cycle phase is stable across restarts.
_PROC_EPOCH = 1_716_940_800


def _proc_drift(t: float) -> float:
    """Smooth -1..1 load oscillation (≈6 min primary + ≈2.3 min secondary)."""
    primary = math.sin((t / 360.0) * 2 * math.pi)
    secondary = math.sin((t / 137.0 + 0.3) * 2 * math.pi)
    return max(-1.0, min(1.0, 0.7 * primary + 0.3 * secondary))


def _opcua_compressor_readings() -> list[ProcessReading] | None:
    """Live OPC UA compressor readings for the Maps process strip, or None (sim fallback).

    When the Killdeer compressor asset (CMP-KILLDEER) is present with live vitals, the
    compressor stage on the Maps page shows the REAL OPC UA values + their good/warn/bad
    status instead of the simulation — including the real CWRU bearing vibration.

    Gated on the seeded asset having live vitals, NOT on the local poll flag (OPCUA_ENABLED):
    a pure consumer (e.g. the cloud reading the edge-published vitals via read_source=dynamo)
    must render the compressor even though it does not poll OPC UA itself. The asset is only
    seeded when OPC UA is configured, so this stays config-gated. Never raises (-> None ->
    simulated fallback). Read-only.
    """
    try:
        from src.main import app_state

        asset = app_state.db.get_asset("CMP-KILLDEER")
        if asset is None:
            return None
        # Apply the configured read source so the Maps compressor renders the EDGE-published
        # vitals: on the cloud (read_source=dynamo) this overlays the Pi's DynamoDB values;
        # on the edge (sqlite) it is a no-op and returns the local poll. True edge-pure.
        with contextlib.suppress(Exception):  # overlay must never break /process
            from src.api.assets import _apply_read_source

            asset = _apply_read_source([asset])[0]
        if not getattr(asset, "vitals", None):
            return None
        by = {v.label: v for v in asset.vitals}
        spec = [
            ("SUCTION PRESSURE", "SUCT", "40001"),
            ("DISCHARGE PRESSURE", "DISCH", "40003"),
            ("GAS TEMP", "GAS", "40007"),
            ("VIBRATION", "VIB", "40017"),  # real CWRU bearing vibration
            ("MOTOR CURRENT", "MOTOR", None),
            ("COMPRESSOR RPM", "RPM", None),
            ("OIL PRESSURE", "OIL", None),
        ]
        out: list[ProcessReading] = []
        for vlabel, rlabel, reg in spec:
            vit = by.get(vlabel)
            if vit is None:
                continue
            out.append(
                ProcessReading(
                    label=rlabel, value=round(vit.raw_value, 1), unit=vit.unit, status=vit.status or "good", reg=reg
                )
            )
        return out or None
    except Exception:  # noqa: BLE001 — must never break /process
        return None


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
    erosion = v(2.4, 0.4)  # sand/erosion probe at the choke (mils/yr) — high-velocity gas service
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
    _elapsed_days = max(0.0, (t - _PROC_EPOCH)) / 86400.0
    accum = 4_125_944.0 + _elapsed_days * 1255.0
    # condensate (LACT) + produced-water (disposal meter) custody totalizers — same
    # monotonic creep so the custody nodes carry believable, ever-increasing totals.
    cond_accum = 86_540.0 + _elapsed_days * 28.0  # LACT net condensate (bbl)
    wat_accum = 71_220.0 + _elapsed_days * 24.0  # produced-water disposal (bbl)
    stn_p = static_p - 12.0  # sales-station line pressure (slight drop downstream of pad custody)

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
                rd("EROS", erosion, "mpy"),  # sand/erosion probe (high-velocity gas service)
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
            # Live OPC UA compressor readings when enabled (real values + status, incl. real
            # CWRU vibration); otherwise the physically-consistent simulation.
            readings=_opcua_compressor_readings()
            or [
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
            readings=[
                rd("COND", oil_lvl, "in", reg="40015"),
                rd("WATER", wat_lvl, "in"),
                # Condensate LACT custody load-out (was a "dark" node — now carries telemetry)
                rd("LACT", cond_bcpd, "BCPD"),
                rd("CTOT", cond_accum, "bbl"),
                # Produced-water disposal meter downstream of the SWD pump
                rd("DISP", bwpd, "BWPD"),
                rd("WTOT", wat_accum, "bbl"),
            ],
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
                # Downstream sales metering station (M2) — was a "dark" node, now metered
                rd("STN", mcfd, "MCFD"),
                rd("STN P", stn_p, "PSIG"),
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
