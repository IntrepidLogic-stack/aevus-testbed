#!/usr/bin/env python3
"""
SCADAPack 470 Modbus TCP Simulator — raw TCP implementation.
No pymodbus server dependency issues. Handles FC3 (read holding) and FC2 (read discrete).
"""
import asyncio
import math
import random
import struct
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("sim")

PROCESS = [
    {"name": "suction_pressure",   "base": 28.5, "min": 22.0, "max": 36.0, "drift": 1.2},
    {"name": "discharge_pressure", "base": 89.0, "min": 78.0, "max": 98.0, "drift": 1.8},
    {"name": "flow_rate",          "base": 125.0,"min": 85.0, "max": 165.0,"drift": 5.0},
    {"name": "gas_temperature",    "base": 142.0,"min": 118.0,"max": 168.0,"drift": 4.0},
    {"name": "ambient_temperature","base": 87.0, "min": 72.0, "max": 108.0,"drift": 3.0},
    {"name": "battery_voltage",    "base": 24.5, "min": 22.8, "max": 26.2, "drift": 0.3},
    {"name": "solar_voltage",      "base": 18.2, "min": 0.0,  "max": 22.5, "drift": 2.0},
    {"name": "tank_level",         "base": 62.0, "min": 8.0,  "max": 96.0, "drift": 0.8},
    {"name": "vibration",          "base": 2.2,  "min": 0.5,  "max": 5.2,  "drift": 0.5},
]
RUN_HOURS_BASE = 18742
current = {p["name"]: p["base"] for p in PROCESS}
start_time = time.time()

# Discrete inputs state
discrete = [True, False, False, False]  # compressor_on, hi_press, lo_batt, comm_fault


def update_values():
    global discrete
    elapsed = time.time() - start_time
    for i, p in enumerate(PROCESS):
        name = p["name"]
        period = 90 + i * 25
        sine = math.sin(2 * math.pi * elapsed / period) * p["drift"] * 0.5
        walk = random.gauss(0, p["drift"] * 0.12)
        if name == "solar_voltage":
            day = math.sin(2 * math.pi * elapsed / 600)
            sine = abs(sine) * max(0.05, (day + 1) / 2)
        if name == "flow_rate":
            dp = current["discharge_pressure"] - current["suction_pressure"]
            sine += (dp - 60) * 0.3
        new_val = current[name] + walk + sine * 0.08
        new_val += (p["base"] - new_val) * 0.015
        current[name] = max(p["min"], min(p["max"], new_val))

    # Update discrete inputs based on process state
    discrete[0] = current["suction_pressure"] > 20 and current["discharge_pressure"] > 70
    discrete[1] = current["discharge_pressure"] > 95
    discrete[2] = current["battery_voltage"] < 23.5
    discrete[3] = False


def get_holding_registers():
    """Build holding register array: 9x Float32 (18 regs) + 1x Uint32 (2 regs) = 20 regs."""
    regs = []
    for p in PROCESS:
        packed = struct.pack('>f', current[p["name"]])
        regs.append((packed[0] << 8) | packed[1])
        regs.append((packed[2] << 8) | packed[3])
    elapsed = time.time() - start_time
    hours = RUN_HOURS_BASE + int(elapsed / 360)
    regs.append((hours >> 16) & 0xFFFF)
    regs.append(hours & 0xFFFF)
    return regs


async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    log.info(f"Client connected: {addr}")
    try:
        while True:
            header = await reader.readexactly(6)  # MBAP header: tid(2) + pid(2) + len(2)
            tid = (header[0] << 8) | header[1]
            pid = (header[2] << 8) | header[3]
            length = (header[4] << 8) | header[5]
            data = await reader.readexactly(length)
            unit_id = data[0]
            fc = data[1]

            if fc == 3:  # Read Holding Registers
                start_addr = (data[2] << 8) | data[3]
                count = (data[4] << 8) | data[5]
                regs = get_holding_registers()
                byte_count = count * 2
                resp = struct.pack('>HHHBBB', tid, pid, 3 + byte_count, unit_id, fc, byte_count)
                for i in range(count):
                    idx = start_addr + i
                    val = regs[idx] if idx < len(regs) else 0
                    resp += struct.pack('>H', val)
                writer.write(resp)

            elif fc == 2:  # Read Discrete Inputs
                start_addr = (data[2] << 8) | data[3]
                count = (data[4] << 8) | data[5]
                byte_count = (count + 7) // 8
                bits = 0
                for i in range(count):
                    idx = start_addr + i
                    if idx < len(discrete) and discrete[idx]:
                        bits |= (1 << i)
                resp = struct.pack('>HHHBBB', tid, pid, 3 + byte_count, unit_id, fc, byte_count)
                for i in range(byte_count):
                    resp += struct.pack('B', (bits >> (i * 8)) & 0xFF)
                writer.write(resp)

            else:  # Unsupported function — return exception
                resp = struct.pack('>HHHBBB', tid, pid, 3, unit_id, fc | 0x80, 1)
                writer.write(resp)

            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionResetError):
        log.info(f"Client disconnected: {addr}")
    finally:
        writer.close()


async def logger_task():
    while True:
        update_values()
        vals = " | ".join(f"{p['name']}={current[p['name']]:.1f}" for p in PROCESS)
        elapsed = time.time() - start_time
        hours = RUN_HOURS_BASE + int(elapsed / 360)
        comp = "RUN" if discrete[0] else "STOP"
        log.info(f"{vals} | hrs={hours} | comp={comp}")
        await asyncio.sleep(5)


async def main():
    asyncio.create_task(logger_task())
    server = await asyncio.start_server(handle_client, '0.0.0.0', 5020)
    log.info("Modbus TCP simulator listening on 0.0.0.0:5020")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
