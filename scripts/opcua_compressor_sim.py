"""Local OPC UA *server* — a compressor source for the Killdeer twin demo.

Hybrid data:
  * Compressor process tags (suction/discharge/interstage/gas temp, motor current,
    RPM, oil pressure, run hours) — simulated with realistic engineering ranges and
    correlated dynamics (discharge > interstage > suction; load-coupled current).
  * VIBRATION + bearing FAULT — REPLAYED from the real CWRU bearing-vibration dataset
    (reference_data/demo/cwru_run.csv), so the vibration carries genuine fault
    signatures and degrades like a real bearing.

This is a self-hosted OPC UA server we control — far closer to a real compressor than
the abstract public sims, while staying clearly a simulation (no customer OT). The
Aevus OPC UA *client* polls it read-only; nothing here writes to anything.

Run:  python scripts/opcua_compressor_sim.py [--endpoint opc.tcp://0.0.0.0:48400/aevus/compressor]
NodeIds are stable strings: ns=2;s=<Name>  (see the tag-map killdeer_compressor.yaml).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import math
import random
from pathlib import Path

from asyncua import Server, ua

_REPO = Path(__file__).resolve().parents[1]
_CWRU = _REPO / "reference_data" / "demo" / "cwru_run.csv"
_DEFAULT_ENDPOINT = "opc.tcp://0.0.0.0:48400/aevus/compressor"
_NS_URI = "http://intrepidlogic.io/aevus/compressor"


def _load_cwru_frames() -> list[dict]:
    """Group cwru_run.csv rows into per-frame dicts {vibration, vibration_velocity, fault}."""
    if not _CWRU.exists():
        return []
    frames: dict[int, dict] = {}
    with _CWRU.open(newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                fr = int(row["frame"])
                frames.setdefault(fr, {})[row["metric"]] = float(row["value"])
            except (KeyError, TypeError, ValueError):
                continue
    return [frames[k] for k in sorted(frames)]


class _Compressor:
    """Realistic, correlated compressor process model (engineering ranges)."""

    def __init__(self) -> None:
        self.t = 0.0
        self.run_hours = 12840.0

    def step(self, dt: float) -> dict[str, float]:
        self.t += dt
        self.run_hours += dt / 3600.0
        # slow load oscillation 0..1 with a little noise
        load = 0.5 + 0.35 * math.sin(self.t / 47.0) + 0.05 * random.uniform(-1, 1)
        load = max(0.0, min(1.0, load))
        suction = 235 + 25 * load + random.uniform(-2, 2)  # ~210..262 PSI
        ratio = 4.7 + 0.3 * load
        discharge = suction * ratio + random.uniform(-8, 8)  # ~1050..1280 PSI
        interstage = 175 + 55 * load + random.uniform(-3, 3)  # °F, between stages
        gas_temp = 92 + 14 * load + random.uniform(-1.5, 1.5)  # °F
        motor_current = 38 + 22 * load + random.uniform(-1, 1)  # A
        rpm = 1140 + 110 * load + random.uniform(-5, 5)
        oil_pressure = 62 - 8 * load + random.uniform(-1.5, 1.5)  # drops slightly under load
        return {
            "SuctionPressure": round(suction, 1),
            "DischargePressure": round(discharge, 1),
            "InterstageTemp": round(interstage, 1),
            "GasTemp": round(gas_temp, 1),
            "MotorCurrent": round(motor_current, 2),
            "CompressorRPM": round(rpm, 0),
            "OilPressure": round(oil_pressure, 1),
            "RunHours": round(self.run_hours, 1),
        }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default=_DEFAULT_ENDPOINT)
    ap.add_argument("--interval", type=float, default=1.0, help="update seconds")
    ap.add_argument("--cwru-step", type=float, default=2.0, help="seconds per CWRU frame")
    args = ap.parse_args()

    frames = _load_cwru_frames()
    print(f"CWRU frames loaded: {len(frames)} (real bearing vibration + fault replay)")

    server = Server()
    await server.init()
    server.set_endpoint(args.endpoint)
    server.set_server_name("Aevus Compressor Simulation (OPC UA)")
    ns = await server.register_namespace(_NS_URI)

    comp = await server.nodes.objects.add_object(ua.NodeId("Compressor", ns), "Compressor")

    async def mkvar(name: str, val: float):
        v = await comp.add_variable(ua.NodeId(name, ns), name, float(val))
        return v

    model = _Compressor()
    init = model.step(0.0)
    nodes = {k: await mkvar(k, v) for k, v in init.items()}
    nodes["Vibration"] = await mkvar("Vibration", 0.6)  # mm/s, REAL CWRU velocity
    nodes["VibrationAccel"] = await mkvar("VibrationAccel", 0.07)  # g, REAL CWRU accel
    nodes["BearingFault"] = await mkvar("BearingFault", 0.0)  # 0 none,1 inner,2 outer,3 ball

    print(f"OPC UA compressor server listening on {args.endpoint}")
    print(f"  namespace index {ns}; nodes: ns={ns};s=SuctionPressure ... ns={ns};s=Vibration")

    fi = 0.0
    async with server:
        while True:
            for k, v in model.step(args.interval).items():
                await nodes[k].write_value(v)
            if frames:
                fr = frames[int(fi) % len(frames)]
                if "vibration_velocity" in fr:
                    await nodes["Vibration"].write_value(round(fr["vibration_velocity"], 3))
                if "vibration" in fr:
                    await nodes["VibrationAccel"].write_value(round(fr["vibration"], 4))
                if "fault" in fr:
                    await nodes["BearingFault"].write_value(float(fr["fault"]))
                fi += args.interval / max(0.1, args.cwru_step)
            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
