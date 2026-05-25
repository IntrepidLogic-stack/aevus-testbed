#!/usr/bin/env python3
"""
SCADAPack 470 Modbus TCP Simulator — Full Wellsite Profile
Simulates complete oil & gas wellsite: compressor, well, separator, tanks, safety.
Handles FC3 (read holding) and FC2 (read discrete).
"""
import asyncio
import logging
import math
import random
import struct
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("sim")

# ── Analog Process Values (Float32 = 2 registers each) ─────────
# Register map: 40001-40054 (27 float32/uint32 values = 54 registers)
PROCESS = [
    # Compressor (40001-40020)
    {"name": "suction_pressure",   "base": 28.5,  "min": 22.0,  "max": 36.0,   "drift": 1.2},
    {"name": "discharge_pressure", "base": 89.0,  "min": 78.0,  "max": 98.0,   "drift": 1.8},
    {"name": "gas_temperature",    "base": 142.0, "min": 118.0, "max": 168.0,  "drift": 4.0},
    {"name": "vibration",          "base": 2.2,   "min": 0.5,   "max": 5.2,    "drift": 0.5},
    {"name": "motor_current",      "base": 85.0,  "min": 65.0,  "max": 105.0,  "drift": 5.0},
    {"name": "compressor_rpm",     "base": 1200,  "min": 900,   "max": 1400,   "drift": 30.0},
    {"name": "interstage_temp",    "base": 195.0, "min": 165.0, "max": 235.0,  "drift": 8.0},
    {"name": "oil_pressure",       "base": 55.0,  "min": 38.0,  "max": 68.0,   "drift": 3.0},
    {"name": "coolant_temp",       "base": 175.0, "min": 150.0, "max": 205.0,  "drift": 6.0},
    # run_hours handled separately (uint32)

    # Well (40021-40032)
    {"name": "casing_pressure",    "base": 320.0, "min": 260.0, "max": 380.0,  "drift": 10.0},
    {"name": "tubing_pressure",    "base": 280.0, "min": 230.0, "max": 330.0,  "drift": 8.0},
    {"name": "flow_rate",          "base": 2.8,   "min": 1.5,   "max": 4.2,    "drift": 0.3},
    {"name": "oil_production_rate","base": 45.0,  "min": 28.0,  "max": 62.0,   "drift": 4.0},
    {"name": "water_cut",          "base": 22.0,  "min": 12.0,  "max": 38.0,   "drift": 3.0},
    {"name": "choke_position",     "base": 65.0,  "min": 30.0,  "max": 90.0,   "drift": 5.0},

    # Production (40033-40044)
    {"name": "separator_pressure", "base": 125.0, "min": 95.0,  "max": 155.0,  "drift": 6.0},
    {"name": "separator_level",    "base": 55.0,  "min": 30.0,  "max": 75.0,   "drift": 5.0},
    {"name": "separator_diff_press","base": 4.5,  "min": 2.0,   "max": 7.5,    "drift": 0.8},
    {"name": "oil_tank_level",     "base": 72.0,  "min": 20.0,  "max": 120.0,  "drift": 3.0},
    {"name": "water_tank_level",   "base": 48.0,  "min": 15.0,  "max": 85.0,   "drift": 2.5},
    {"name": "lact_meter_rate",    "base": 8.5,   "min": 4.0,   "max": 14.0,   "drift": 1.5},

    # Power (40045-40048)
    {"name": "battery_voltage",    "base": 24.5,  "min": 22.8,  "max": 26.2,   "drift": 0.3},
    {"name": "solar_voltage",      "base": 18.2,  "min": 0.0,   "max": 22.5,   "drift": 2.0},

    # Environment (40049-40050)
    {"name": "ambient_temperature","base": 87.0,  "min": 72.0,  "max": 108.0,  "drift": 3.0},

    # Safety (40051-40054)
    {"name": "h2s_level",          "base": 1.2,   "min": 0.0,   "max": 4.5,    "drift": 0.4},
    {"name": "lel_level",          "base": 3.0,   "min": 0.0,   "max": 8.0,    "drift": 0.8},
]

RUN_HOURS_BASE = 18742
current = {p["name"]: p["base"] for p in PROCESS}
start_time = time.time()

# ── Discrete Inputs (12 coils) ──────────────────────────────────
# 10001-10012
discrete_names = [
    "compressor_running",    # 10001
    "compressor_loaded",     # 10002
    "high_pressure_alarm",   # 10003
    "high_temp_alarm",       # 10004
    "low_oil_pressure",      # 10005
    "low_battery_alarm",     # 10006
    "communication_fault",   # 10007
    "esd_activated",         # 10008
    "h2s_alarm",             # 10009
    "lel_alarm",             # 10010
    "flare_active",          # 10011
    "tank_high_level",       # 10012
]
discrete = [True, True, False, False, False, False, False, False, False, False, True, False]


def update_values():
    global discrete
    elapsed = time.time() - start_time
    for i, p in enumerate(PROCESS):
        name = p["name"]
        period = 90 + i * 25
        sine = math.sin(2 * math.pi * elapsed / period) * p["drift"] * 0.5
        walk = random.gauss(0, p["drift"] * 0.12)

        # Solar follows day/night cycle
        if name == "solar_voltage":
            day = math.sin(2 * math.pi * elapsed / 600)
            sine = abs(sine) * max(0.05, (day + 1) / 2)

        # Flow correlates with differential pressure
        if name == "flow_rate":
            dp = current["discharge_pressure"] - current["suction_pressure"]
            sine += (dp - 60) * 0.003

        # Oil production loosely follows flow rate
        if name == "oil_production_rate":
            sine += (current["flow_rate"] - 2.8) * 2.0

        # Water cut drifts slowly upward over time (realistic decline curve)
        if name == "water_cut":
            sine += elapsed * 0.00001

        new_val = current[name] + walk + sine * 0.08
        new_val += (p["base"] - new_val) * 0.015
        current[name] = max(p["min"], min(p["max"], new_val))

    # ── Derive discrete states from process values ──
    discrete[0] = current["suction_pressure"] > 20 and current["discharge_pressure"] > 70  # compressor_running
    discrete[1] = discrete[0] and current["motor_current"] > 70  # compressor_loaded
    discrete[2] = current["discharge_pressure"] > 95  # high_pressure_alarm
    discrete[3] = current["interstage_temp"] > 225 or current["coolant_temp"] > 200  # high_temp_alarm
    discrete[4] = current["oil_pressure"] < 40  # low_oil_pressure
    discrete[5] = current["battery_voltage"] < 23.5  # low_battery_alarm
    discrete[6] = False  # communication_fault
    discrete[7] = False  # esd_activated
    discrete[8] = current["h2s_level"] > 4.0  # h2s_alarm
    discrete[9] = current["lel_level"] > 7.0  # lel_alarm
    discrete[10] = True  # flare_active (pilot lit)
    discrete[11] = current["oil_tank_level"] > 115  # tank_high_level


def get_holding_registers():
    """Build holding register array: 26x Float32 + 1x Uint32 = 54 registers."""
    regs = []

    # First 9 floats (compressor analogs, 40001-40018)
    for p in PROCESS[:9]:
        packed = struct.pack('>f', current[p["name"]])
        regs.append((packed[0] << 8) | packed[1])
        regs.append((packed[2] << 8) | packed[3])

    # Run hours as uint32 (40019-40020)
    elapsed = time.time() - start_time
    hours = RUN_HOURS_BASE + int(elapsed / 360)
    regs.append((hours >> 16) & 0xFFFF)
    regs.append(hours & 0xFFFF)

    # Remaining 17 floats (well + production + power + environment + safety, 40021-40054)
    for p in PROCESS[9:]:
        packed = struct.pack('>f', current[p["name"]])
        regs.append((packed[0] << 8) | packed[1])
        regs.append((packed[2] << 8) | packed[3])

    return regs


async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    log.info(f"Client connected: {addr}")
    try:
        while True:
            header = await reader.readexactly(6)
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

            else:
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
        core = (
            f"SP={current['suction_pressure']:.1f} "
            f"DP={current['discharge_pressure']:.1f} "
            f"FR={current['flow_rate']:.2f} "
            f"OP={current['oil_production_rate']:.1f} "
            f"WC={current['water_cut']:.1f}% "
            f"CP={current['casing_pressure']:.0f} "
            f"TP={current['tubing_pressure']:.0f} "
            f"H2S={current['h2s_level']:.1f} "
            f"RPM={current['compressor_rpm']:.0f}"
        )
        comp = "RUN" if discrete[0] else "STOP"
        log.info(f"{core} | {comp}")
        await asyncio.sleep(5)


async def main():
    asyncio.create_task(logger_task())
    server = await asyncio.start_server(handle_client, '0.0.0.0', 5020)
    log.info("Modbus TCP simulator listening on 0.0.0.0:5020 — full wellsite profile")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
