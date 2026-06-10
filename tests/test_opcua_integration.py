"""OPC UA live integration test (P5/P6) — runs against a real OPC UA server.

Skipped unless OPCUA_INTEGRATION_ENDPOINT is set, so the default unit suite stays
offline. To run locally (or in CI) start a Microsoft OPC PLC container:

    docker run -d --name opcplc -p 50000:50000 \
        mcr.microsoft.com/iotedge/opc-plc:latest \
        --pn=50000 --unsecuretransport --autoaccept --hostname=localhost

    OPCUA_INTEGRATION_ENDPOINT=opc.tcp://localhost:50000 pytest tests/test_opcua_integration.py

This exercises the full path against a real server: collector -> RawTelemetry ->
normalizer -> status, including a moving anomaly signal (SpikeData) tripping a
threshold. Read-only throughout.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from src.collectors.opcua_client import OPCUAClientCollector, OPCUANodeSpec
from src.engine.normalizer import normalize_batch

_EP = os.environ.get("OPCUA_INTEGRATION_ENDPOINT")
pytestmark = pytest.mark.skipif(
    not _EP,
    reason="set OPCUA_INTEGRATION_ENDPOINT (e.g. opc.tcp://localhost:50000 with opc-plc) to run",
)

# opc-plc standard simulation nodes (Microsoft OPC PLC):
#   SpikeData  — sine -100..100 with spikes  -> map to vibration (crosses 4.5/7.1)
#   FastUInt1  — monotonic counter           -> map to run_hours (info, no status)
#   Boiler CurrentTemperature (ns=4;i=6211)  -> map to gas_temperature
_SPECS = [
    OPCUANodeSpec("ns=3;s=SpikeData", "vibration", "mm/s", "anomaly"),
    OPCUANodeSpec("ns=3;s=FastUInt1", "run_hours", "hours", "sim"),
    OPCUANodeSpec("ns=4;i=6211", "gas_temperature", "degF", "boiler"),
]


async def test_opcua_live_container_end_to_end():
    col = OPCUAClientCollector("OPCUA-IT", _EP, _SPECS, poll_interval=1)
    polls: list[list] = []
    try:
        for _ in range(12):
            polls.append(await col.safe_poll())
            await asyncio.sleep(0.4)
    finally:
        await col.aclose()

    flat = [r for p in polls for r in p]
    assert flat, "no readings from the OPC UA server"
    assert all(r.source == "opcua" for r in flat)
    assert all(r.opcua_node for r in flat)  # NodeId carried through

    # the anomaly signal must actually move across polls (proves live ingest)
    vib_values = [r.value for p in polls for r in p if r.metric == "vibration"]
    assert len(set(vib_values)) > 1, "vibration value never changed — not live"

    # normalizer runs on real container data: vibration carries a status, run_hours is info
    first = {v.label: v for v in normalize_batch(polls[0])}
    assert first["VIBRATION"].status in ("good", "warn", "bad")
    assert first["RUN HOURS"].status == ""

    # the SpikeData anomaly trips a non-good vibration status at least once over the window
    seen_status = set()
    for p in polls:
        for v in normalize_batch(p):
            if v.label == "VIBRATION":
                seen_status.add(v.status)
    assert {"warn", "bad"} & seen_status, f"anomaly never tripped a threshold; saw {seen_status}"
