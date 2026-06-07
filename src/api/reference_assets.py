"""Flag-gated REFERENCE assets appended to /assets (real recorded data).

OFF by default (settings.reference_assets_enabled). When enabled, surfaces two
labeled REFERENCE assets fed by the committed demo slices:
  * REF-CWRU   — real CWRU bearing vibration (accel RMS flags the seeded fault)
  * REF-MORRIS — real Morris gas-pipeline Modbus (pressure range/validity check)

These are NOT live lab hardware, NOT the simulated Killdeer twin, and NOT a
customer feed — they are recorded research datasets, attributed in vendor/model.
This module NEVER touches the SQLite registry and NEVER raises into the endpoint
(any error -> []), so it cannot break the live /assets response.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from pathlib import Path

import structlog

from src.config import settings
from src.models.asset import Asset
from src.models.telemetry import VitalSign

log = structlog.get_logger().bind(component="reference_assets")
_DEMO = Path(__file__).resolve().parents[2] / "reference_data" / "demo"
_ADVANCE_EVERY_S = 2.0

_state: dict = {"init": False, "cwru": None, "morris": None, "last": 0.0, "cwru_f": [], "morris_f": []}


def _ensure_init() -> None:
    if _state["init"]:
        return
    from src.collectors.reference_replay import ReferenceReplayCollector

    cw, mo = _DEMO / "cwru_run.csv", _DEMO / "morris_slice.csv"
    _state["cwru"] = ReferenceReplayCollector("REF-CWRU", cw) if cw.exists() else None
    _state["morris"] = ReferenceReplayCollector("REF-MORRIS", mo) if mo.exists() else None
    _state["init"] = True


def _frame_map(rows: list[dict[str, str]]) -> dict[str, tuple[float, str]]:
    out: dict[str, tuple[float, str]] = {}
    for r in rows:
        try:
            out[r["metric"]] = (float(r["value"]), r.get("unit", ""))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _vital(label: str, value: float, unit: str, status: str = "") -> VitalSign:
    txt = f"{value:.3g} {unit}".strip() if unit else f"{value:.3g}"
    return VitalSign(label=label, value=txt, raw_value=value, unit=unit, status=status)


def _cwru_asset(fm: dict[str, tuple[float, str]]) -> Asset:
    accel = fm.get("vibration", (0.0, "g"))[0]
    vel = fm.get("vibration_velocity", (0.0, "mm/s"))[0]
    fault = fm.get("fault", (0.0, "state"))[0]
    status = "bad" if accel > 0.12 else ("warn" if accel > 0.09 else "good")
    health = 35 if status == "bad" else (70 if status == "warn" else 96)
    fault_name = {0: "none", 1: "inner-race", 2: "outer-race", 3: "ball"}.get(int(fault), "n/a")
    return Asset(
        id="REF-CWRU",
        type="sensor",
        status=status,
        name="Reference — CWRU Bearing",
        location="Reference dataset (CWRU Bearing Data Center)",
        health=health,
        last_seen=datetime.now(UTC),
        vendor="Case Western Reserve Univ.",
        model="Bearing Data Center (vibration)",
        protocol="reference",
        vitals=[
            _vital("VIBRATION", accel, "g", status),
            _vital("VIB VELOCITY", vel, "mm/s"),
            VitalSign(
                label="FAULT", value=fault_name, raw_value=fault, unit="class", status="bad" if fault >= 1 else "good"
            ),
        ],
    )


def _morris_asset(fm: dict[str, tuple[float, str]]) -> Asset:
    press = fm.get("pipe_pressure", (0.0, "PSI"))[0]
    setp = fm.get("setpoint", (0.0, "PSI"))[0]
    invalid = (not math.isfinite(press)) or press < -50.0 or press > 200.0
    status = "warn" if invalid else "good"
    vitals = [_vital("PRESSURE", press, "PSI", "warn" if invalid else "good")]
    if math.isfinite(setp):
        vitals.append(_vital("SETPOINT", setp, "PSI"))
    for m, lbl in (("control_mode", "CTRL MODE"), ("pump", "PUMP"), ("solenoid", "SOLENOID")):
        if m in fm:
            vitals.append(_vital(lbl, fm[m][0], ""))
    return Asset(
        id="REF-MORRIS",
        type="rtu",
        status=status,
        name="Reference — Morris Gas Pipeline",
        location="Reference dataset (MSU / UAH ICS)",
        health=60 if invalid else 95,
        last_seen=datetime.now(UTC),
        vendor="Mississippi State / UAH",
        model="Gas-Pipeline ICS (Modbus)",
        protocol="modbus",
        vitals=vitals,
    )


def reference_assets() -> list[Asset]:
    """Return the reference assets when enabled; [] otherwise or on any error."""
    if not settings.reference_assets_enabled:
        return []
    try:
        _ensure_init()
        now = time.monotonic()
        if now - _state["last"] >= _ADVANCE_EVERY_S or not _state["cwru_f"]:
            _state["last"] = now
            if _state["cwru"]:
                _state["cwru_f"] = _state["cwru"].advance()
            if _state["morris"]:
                _state["morris_f"] = _state["morris"].advance()
        out: list[Asset] = []
        if _state["cwru_f"]:
            out.append(_cwru_asset(_frame_map(_state["cwru_f"])))
        if _state["morris_f"]:
            out.append(_morris_asset(_frame_map(_state["morris_f"])))
        return out
    except Exception as e:  # noqa: BLE001 — must never break /assets
        log.warning("reference_assets_failed", error=str(e))
        return []
