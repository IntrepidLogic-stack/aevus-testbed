#!/usr/bin/env python3
"""
SCADAPack 470 Register Writer — LAB BENCH FIXTURE (not part of the platform).

Seeds a *test* SCADAPack with simulated oil & gas process values so the
collector read-path has realistic data. This is the ONE sanctioned write to
field equipment, so it lives OUTSIDE the importable `src/` app package (which
is proven write-free by tests/test_il9000.py) and is gated by the IL-009
interlock: it refuses to run unless an on-site technician sets
AEVUS_ALLOW_BENCH_WRITE=1 deliberately.

    AEVUS_ALLOW_BENCH_WRITE=1 python tools/register_writer.py
"""

import asyncio
import math
import os
import random
import struct
import sys
import time

from pymodbus.client import AsyncModbusTcpClient

# Import the interlock from the app package (tools/ runs from the repo root).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.il9000 import assert_read_only  # noqa: E402

HOST = "172.16.1.200"
PORT = 502

# Register map — Float32 = 2 registers each, matching collector
# address is 0-based offset (40001 = 0, 40003 = 2, etc.)
REGISTERS = [
    {"addr": 0, "name": "suction_pressure", "base": 28.5, "min": 24.0, "max": 34.0, "drift": 0.8},
    {"addr": 2, "name": "discharge_pressure", "base": 89.0, "min": 80.0, "max": 98.0, "drift": 1.2},
    {"addr": 4, "name": "flow_rate", "base": 125.0, "min": 90.0, "max": 160.0, "drift": 4.0},
    {"addr": 6, "name": "gas_temperature", "base": 142.0, "min": 120.0, "max": 165.0, "drift": 3.0},
    {"addr": 8, "name": "ambient_temperature", "base": 87.0, "min": 75.0, "max": 105.0, "drift": 2.0},
    {"addr": 10, "name": "battery_voltage", "base": 24.5, "min": 23.0, "max": 26.0, "drift": 0.2},
    {"addr": 12, "name": "solar_voltage", "base": 18.2, "min": 0.0, "max": 22.0, "drift": 1.5},
    {"addr": 14, "name": "tank_level", "base": 62.0, "min": 10.0, "max": 95.0, "drift": 0.5},
    {"addr": 16, "name": "vibration", "base": 2.2, "min": 0.8, "max": 4.8, "drift": 0.4},
]
# run_hours is uint32 at address 18 (register 40019)
RUN_HOURS_ADDR = 18
RUN_HOURS_BASE = 18742

# Discrete inputs (coils) at address 0-3 (10001-10004)
# 10001=compressor_running, 10002=high_pressure, 10003=low_battery, 10004=comm_fault

current = {r["name"]: r["base"] for r in REGISTERS}
start_time = time.time()


def float32_to_regs(val):
    """Convert float to two 16-bit Modbus registers (big-endian word order)."""
    packed = struct.pack(">f", val)
    hi = (packed[0] << 8) | packed[1]
    lo = (packed[2] << 8) | packed[3]
    return [hi, lo]


def uint32_to_regs(val):
    """Convert uint32 to two 16-bit registers (big-endian)."""
    return [(val >> 16) & 0xFFFF, val & 0xFFFF]


def compute_values():
    elapsed = time.time() - start_time
    for i, reg in enumerate(REGISTERS):
        name = reg["name"]
        # Sine oscillation
        period = 120 + i * 30
        sine = math.sin(2 * math.pi * elapsed / period) * reg["drift"] * 0.6
        # Random walk
        walk = random.gauss(0, reg["drift"] * 0.15)
        # Solar follows daylight cycle
        if name == "solar_voltage":
            hour_factor = math.sin(2 * math.pi * elapsed / 600)
            sine = abs(sine) * max(0.1, (hour_factor + 1) / 2)
        new_val = current[name] + walk + sine * 0.05
        # Mean reversion
        new_val += (reg["base"] - new_val) * 0.02
        new_val = max(reg["min"], min(reg["max"], new_val))
        current[name] = new_val


async def write_registers():
    # IL-009 interlock: refuse to write to field equipment unless a technician
    # has deliberately enabled the bench override on-site.
    assert_read_only("scadapack_bench_seed_write")
    print(f"Connecting to SCADAPack at {HOST}:{PORT}...")
    client = AsyncModbusTcpClient(HOST, port=PORT)
    await client.connect()
    if not client.connected:
        print("ERROR: Could not connect")
        return
    print("Connected — writing Float32 registers every 5 seconds")

    while True:
        try:
            compute_values()
            elapsed = time.time() - start_time

            # Write each Float32 register pair
            for reg in REGISTERS:
                regs = float32_to_regs(current[reg["name"]])
                result = await client.write_registers(reg["addr"], regs)
                if result.isError():
                    print(f"Write error at {reg['addr']}: {result}")

            # Write run_hours as uint32
            hours = RUN_HOURS_BASE + int(elapsed / 360)  # increment every 6 min for demo
            regs = uint32_to_regs(hours)
            await client.write_registers(RUN_HOURS_ADDR, regs)

            # Write discrete inputs (coils) — compressor running, alarms OK
            await client.write_coil(0, True)  # compressor running
            await client.write_coil(1, False)  # high pressure alarm off
            await client.write_coil(2, False)  # low battery alarm off
            await client.write_coil(3, False)  # comm fault off

            vals = " | ".join(f"{r['name']}={current[r['name']]:.1f}" for r in REGISTERS)
            print(f"[{time.strftime('%H:%M:%S')}] {vals} | run_hours={hours}")

            await asyncio.sleep(5)
        except Exception as e:
            print(f"Error: {e} — reconnecting in 10s")
            await asyncio.sleep(10)
            try:
                await client.connect()
            except Exception as reconnect_err:  # noqa: BLE001 - reconnect tolerates any failure
                print(f"reconnect failed: {reconnect_err}")


if __name__ == "__main__":
    asyncio.run(write_registers())
