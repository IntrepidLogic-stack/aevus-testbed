"""Pearl normalization engine — Rickerson Scale (P0).

Maps raw per-device-class telemetry to a 0–100 normalized health score per
the spec in docs/RICKERSON_SCALE_SPEC.md.

═══════════════════════════════════════════════════════════════════════════
TRADE SECRET — INTREPID LOGIC PROPRIETARY
═══════════════════════════════════════════════════════════════════════════
The piecewise normalization curves and component weights below are the core
IP of the Rickerson Scale widget. They are deliberately ALGORITHMIC (not
linear) because real RF/comm health is non-linear and a linear map produces
misleading scores that a domain expert (Rickerson, RF eng) would see through
on first inspection.

Rules of engagement:
  • This module returns only the final 0–100 score + status band.
  • The API layer (src/api/pearls.py) MUST NOT echo raw input vitals back
    in the same response — sample-poll reverse-engineering is the attack.
  • Tuning constants live here and are version-controlled in the private
    repo only; never expose in tooltips, exports, or client-side JS.
  • Industry-sourced thresholds (Trio datasheet RSSI bands, ISA-101 alarm
    bands, Modbus default comm-success expectations) are cited in comments
    for our own RTP/P-008 CIP record.

Status band convention (matches handoff + spec):
  100         healthy
  60–99       good   (#10D478)
  30–59       warn   (#FBBF24)
  0–29        bad    (#EF4444)
  None        offline/unknown (#6B7280, gray)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src.models.asset import Asset

Status = Literal["good", "warn", "bad", "offline"]


# ── Piecewise helpers ──────────────────────────────────────────────────
def _piecewise(value: float, points: list[tuple[float, float]]) -> float:
    """Linear interpolation between (input, output) anchor points.

    `points` MUST be sorted by input. Values outside the range are clamped
    to the nearest anchor's output (no extrapolation — keeps the curve
    honest at the extremes).
    """
    if not points:
        return 0.0
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        if x0 <= value <= x1:
            if x1 == x0:
                return y0
            t = (value - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return points[-1][1]


def _band(score: float | None) -> Status:
    if score is None:
        return "offline"
    if score >= 60:
        return "good"
    if score >= 30:
        return "warn"
    return "bad"


def _vital(asset: Asset, label: str) -> float | None:
    """Pull a numeric vital by label. Returns None if absent or non-numeric."""
    for v in asset.vitals or []:
        if v.label == label and isinstance(v.raw_value, int | float):
            return float(v.raw_value)
    return None


# ── Per-device-class curves (TRADE SECRET) ─────────────────────────────
# Sourced from: Trio JR900 datasheet RSSI sensitivity table (-90 dBm =
# link floor, -85 = warn boundary, -70 = clean above-noise headroom);
# ISA-101 alarm bands for temperature/voltage; midstream-RTU comm-success
# defaults (≥98% = healthy in Wonderware-class deployments).
_RSSI_CURVE = [
    (-110.0, 0.0),  # below link floor — dead
    (-95.0, 20.0),  # critical — at margin
    (-90.0, 40.0),  # link floor, warn band start
    (-85.0, 60.0),  # warn → good boundary
    (-75.0, 85.0),  # comfortable headroom
    (-65.0, 98.0),  # excellent
    (-50.0, 100.0),  # ceiling
]

_TEMP_RADIO_CURVE = [
    (-20.0, 60.0),
    (0.0, 80.0),
    (45.0, 100.0),  # nominal band
    (60.0, 70.0),  # ISA-101 warn boundary
    (75.0, 30.0),  # critical
    (85.0, 0.0),  # thermal shutdown territory
]

_VOLTAGE_RADIO_CURVE = [
    (9.0, 0.0),
    (10.5, 30.0),
    (11.5, 60.0),  # Trio low-volt warn
    (12.0, 85.0),
    (13.5, 100.0),
    (15.0, 100.0),
    (16.0, 70.0),
    (17.0, 20.0),  # over-volt risk
]

_BATTERY_RTU_CURVE = [
    (10.0, 0.0),
    (11.5, 20.0),
    (12.0, 60.0),  # SCADAPack low-batt warn
    (12.6, 85.0),
    (13.2, 100.0),
    (14.0, 100.0),
]

_CPU_CURVE = [
    (0.0, 100.0),
    (50.0, 95.0),
    (70.0, 70.0),  # default warn
    (85.0, 40.0),
    (95.0, 10.0),
    (100.0, 0.0),
]

_LATENCY_MS_CURVE = [
    (0.0, 100.0),
    (10.0, 95.0),  # sub-10ms = P-008 patent-relevant edge claim
    (50.0, 80.0),
    (200.0, 50.0),  # warn boundary
    (500.0, 20.0),
    (1000.0, 0.0),
]

_COMM_SUCCESS_CURVE = [
    (0.0, 0.0),
    (90.0, 30.0),
    (98.0, 60.0),  # Wonderware-class healthy boundary
    (99.5, 90.0),
    (100.0, 100.0),
]


# ── Component scorers ──────────────────────────────────────────────────
def _radio_rssi_component(a: Asset) -> float | None:
    rssi = _vital(a, "RSSI")
    if rssi is None:
        return None
    return _piecewise(rssi, _RSSI_CURVE)


def _radio_link_component(a: Asset) -> float | None:
    """Link state is binary-ish but tx errors pull it down. Returns None
    if no link telemetry exists (so the composite can re-weight)."""
    link = _vital(a, "LINK STATE")
    if link is None:
        return None
    tx_err = _vital(a, "TX ERRORS") or 0
    rx_err = _vital(a, "RX ERRORS") or 0
    base = 100.0 if link >= 1 else 0.0
    err_penalty = min(40.0, (tx_err + rx_err) * 0.5)
    return max(0.0, base - err_penalty)


def _radio_thermal_component(a: Asset) -> float | None:
    temp = _vital(a, "TEMPERATURE")
    if temp is None:
        return None
    return _piecewise(temp, _TEMP_RADIO_CURVE)


def _radio_power_component(a: Asset) -> float | None:
    v = _vital(a, "VOLTAGE")
    if v is None:
        return None
    return _piecewise(v, _VOLTAGE_RADIO_CURVE)


def _radio_latency_component(a: Asset) -> float | None:
    lat = _vital(a, "LATENCY")
    if lat is None:
        return None
    return _piecewise(lat, _LATENCY_MS_CURVE)


# ── Per-device-class composite scorers ─────────────────────────────────
def score_radio(asset: Asset) -> int | None:
    """Trio JR900 / generic SNMP radio.

    Weighted composite of RSSI (40%), link/errors (25%), thermal (15%),
    power (10%), latency (10%). Components that return None are dropped
    and remaining weights are re-normalized — a radio with no temp sensor
    still gets a meaningful score.
    """
    components = [
        (_radio_rssi_component(asset), 0.40),
        (_radio_link_component(asset), 0.25),
        (_radio_thermal_component(asset), 0.15),
        (_radio_power_component(asset), 0.10),
        (_radio_latency_component(asset), 0.10),
    ]
    available = [(s, w) for s, w in components if s is not None]
    if not available:
        return None
    weight_sum = sum(w for _, w in available)
    if weight_sum == 0:
        return None
    score = sum(s * w for s, w in available) / weight_sum
    # Hard floor: a radio with link down is critical regardless of how good
    # its thermals/voltage look. Without this short-circuit the composite
    # average misleads operators (RF eng review caught this 2026-05-30).
    link = _vital(asset, "LINK STATE")
    if link is not None and link < 1:
        score = min(score, 25.0)
    return int(round(score))


def score_router(asset: Asset) -> int | None:
    """MikroTik / generic router. CPU + interface health weighted."""
    cpu = _vital(asset, "CPU LOAD")
    cpu_score = _piecewise(cpu, _CPU_CURVE) if cpu is not None else None
    # Interface error rate proxy — sum of errors across vitals
    err_total = 0.0
    err_seen = False
    for v in asset.vitals or []:
        if "ERROR" in v.label.upper() and isinstance(v.raw_value, int | float):
            err_total += float(v.raw_value)
            err_seen = True
    iface_score = max(0.0, 100.0 - min(80.0, err_total * 0.1)) if err_seen else None

    parts = [(cpu_score, 0.6), (iface_score, 0.4)]
    available = [(s, w) for s, w in parts if s is not None]
    if not available:
        # Fall back to "alive but unmeasured" — a reachable router with no
        # CPU sensor still beats offline
        return 70 if asset.status != "offline" else None
    weight_sum = sum(w for _, w in available)
    return int(round(sum(s * w for s, w in available) / weight_sum))


def score_switch(asset: Asset) -> int | None:
    """Cisco Catalyst / generic switch — proxies aggregation tier in testbed."""
    return score_router(asset)  # same shape; CPU + iface errors


def score_rtu(asset: Asset) -> int | None:
    """SCADAPack 470 / generic RTU. Comm success + battery + alarms."""
    if asset.status == "offline":
        return None
    batt = _vital(asset, "BATTERY")
    if batt is None:
        batt = _vital(asset, "BATTERY VOLTAGE")
    batt_score = _piecewise(batt, _BATTERY_RTU_CURVE) if batt is not None else None

    # Active discrete alarms drag score
    alarm_penalty = 0.0
    for v in asset.vitals or []:
        if "ALARM" in v.label.upper() and v.value == "ACTIVE":
            alarm_penalty += 25.0
    comm_score = max(0.0, 100.0 - alarm_penalty)

    parts = [(batt_score, 0.5), (comm_score, 0.5)]
    available = [(s, w) for s, w in parts if s is not None]
    if not available:
        return 50
    weight_sum = sum(w for _, w in available)
    return int(round(sum(s * w for s, w in available) / weight_sum))


def score_edge(asset: Asset) -> int | None:
    """Raspberry Pi edge collector — service health + CPU."""
    cpu = _vital(asset, "CPU LOAD")
    cpu_score = _piecewise(cpu, _CPU_CURVE) if cpu is not None else None
    mem = _vital(asset, "MEMORY USED")
    mem_score = _piecewise(mem, _CPU_CURVE) if mem is not None else None
    parts = [(cpu_score, 0.6), (mem_score, 0.4)]
    available = [(s, w) for s, w in parts if s is not None]
    if not available:
        return 80 if asset.status != "offline" else None
    weight_sum = sum(w for _, w in available)
    return int(round(sum(s * w for s, w in available) / weight_sum))


def score_scada_host(asset: Asset) -> int | None:
    """SCADA app host — proxy to edge for testbed."""
    return score_edge(asset)


def score_hmi(latency_ms: float | None, session_active: bool) -> int | None:
    """Browser HMI node — heartbeat from rad-hover-live.js (P0d)."""
    if not session_active:
        return None
    if latency_ms is None:
        return 80
    return int(round(_piecewise(latency_ms, _LATENCY_MS_CURVE)))


# ── Top-level dispatch ─────────────────────────────────────────────────
_DISPATCH = {
    "radio": score_radio,
    "router": score_router,
    "switch": score_switch,
    "rtu": score_rtu,
    "edge": score_edge,
    "scada_host": score_scada_host,
    "sensor": lambda a: 80 if a.status != "offline" else None,
}


def score_asset(asset: Asset) -> tuple[int | None, Status]:
    """Score any asset; returns (0-100 or None, status band)."""
    if asset.status == "offline":
        return None, "offline"
    scorer = _DISPATCH.get(asset.type)
    if scorer is None:
        return None, "offline"
    score = scorer(asset)
    return score, _band(score)
