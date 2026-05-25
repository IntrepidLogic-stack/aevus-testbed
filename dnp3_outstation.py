#!/usr/bin/env python3
"""
Aevus — DNP3 Outstation Simulator
Simulates a gas pipeline meter station RTU responding to DNP3 master polls.

Runs as a TCP server on port 20000, responding to READ requests with
realistic EFM, gas quality, valve, power, and pipeline data.

Usage:
    python3 dnp3_outstation.py [--port 20000] [--addr 10]

This simulates what a real field RTU (e.g., ABB TotalFlow, Emerson ROC800,
or Bristol ControlWave) would respond with over DNP3.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import random
import struct
import time

# DNP3 Constants
DNP3_START = 0x0564
FUNC_READ = 0x01
FUNC_RESPONSE = 0x81
GROUP_BINARY_INPUT = 1
GROUP_COUNTER = 20
GROUP_ANALOG_INPUT = 30
GROUP_CLASS_0 = 60
QUAL_ALL_POINTS = 0x06
QUAL_RANGE_8BIT = 0x00
QUAL_RANGE_16BIT = 0x01

# CRC table
_CRC_TABLE = None

def _build_crc_table():
    global _CRC_TABLE
    _CRC_TABLE = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA6BC
            else:
                crc >>= 1
        _CRC_TABLE.append(crc & 0xFFFF)

def _crc16(data: bytes) -> int:
    if _CRC_TABLE is None:
        _build_crc_table()
    crc = 0x0000
    for b in data:
        crc = (_CRC_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)) & 0xFFFF
    return crc ^ 0xFFFF


class MeterStationSimulator:
    """Simulates a gas pipeline meter station with realistic data."""

    def __init__(self):
        self._tick = 0
        self._start_time = time.time()
        self._total_volume = 125840.0  # MCF accumulated
        self._total_energy = 132580.0  # MMBTU accumulated
        self._comm_success = 0
        self._comm_fail = 0

    def _sim(self, base, drift, noise):
        """Generate a value with sinusoidal drift and noise."""
        t = self._tick * 0.03
        return base + drift * math.sin(t) + random.gauss(0, noise)

    def get_analogs(self) -> dict[int, float]:
        """Return analog input values by index."""
        self._tick += 1
        hour = (time.time() / 3600) % 24

        # Flow is higher during daytime operations
        flow_factor = 1.0 + 0.3 * math.sin((hour - 6) / 12 * math.pi)

        # Solar voltage follows daylight
        solar = max(0, 18.5 * math.sin(max(0, (hour - 6) / 12 * math.pi)))

        self._total_volume += 2.8 * flow_factor / 3600 * 10  # accumulate per poll
        self._total_energy += 2.95 * flow_factor / 3600 * 10

        return {
            # EFM
            0:  round(self._sim(45.2, 8.0, 1.5), 2),      # differential_pressure inH2O
            1:  round(self._sim(485.0, 15.0, 3.0), 1),     # static_pressure PSIG
            2:  round(self._sim(72.5, 5.0, 1.0), 1),       # flow_temperature °F
            3:  round(self._sim(2.8, 0.4, 0.1) * flow_factor, 2),  # flow_rate MCFD
            4:  round(self._total_volume, 1),               # accumulated_volume MCF
            5:  round(self._sim(2.95, 0.3, 0.1) * flow_factor, 2), # energy_rate MMBTU/D

            # Gas Quality
            6:  round(self._sim(1028.0, 5.0, 1.0), 1),     # btu_content BTU/CF
            7:  round(self._sim(0.608, 0.005, 0.001), 4),   # specific_gravity
            8:  round(self._sim(0.82, 0.1, 0.02), 2),       # co2_content %
            9:  round(max(0, self._sim(0.3, 0.2, 0.05)), 1), # h2s_content PPM

            # Valve / Regulator
            10: round(self._sim(520.0, 20.0, 5.0), 1),     # upstream_pressure PSIG
            11: round(self._sim(485.0, 15.0, 3.0), 1),     # downstream_pressure PSIG
            12: round(self._sim(72.0, 5.0, 1.0), 1),       # valve_position %

            # Power
            13: round(self._sim(13.1, 0.3, 0.05), 2),      # battery_voltage VDC
            14: round(max(0, solar + random.gauss(0, 0.3)), 1), # solar_voltage VDC
            15: round(max(0, solar * 0.15 + random.gauss(0, 0.02)), 2), # charge_current A

            # Environment
            16: round(self._sim(92.0, 10.0, 2.0), 1),      # enclosure_temp °F
            17: round(self._sim(85.0, 8.0, 1.5), 1),       # ambient_temp °F

            # Pipeline
            18: round(self._sim(490.0, 12.0, 3.0), 1),     # line_pressure PSIG
            19: round(self._sim(74.0, 4.0, 1.0), 1),       # line_temperature °F
        }

    def get_binaries(self) -> dict[int, bool]:
        """Return binary input values by index."""
        return {
            0: True,   # valve_open
            1: False,  # valve_closed
            2: False,  # high_pressure_alarm
            3: False,  # low_pressure_alarm
            4: False,  # high_temp_alarm
            5: False,  # low_battery_alarm
            6: True,   # communication_active
            7: False,  # esd_activated
            8: False,  # h2s_alarm
            9: False,  # tamper_detect
        }

    def get_counters(self) -> dict[int, int]:
        """Return counter values by index."""
        self._comm_success += 1
        return {
            0: int(self._total_volume),     # total_volume MCF
            1: int(self._total_energy),     # total_energy MMBTU
            2: self._comm_success,          # comm_success_count
            3: self._comm_fail,             # comm_failure_count
        }


class DNP3OutstationServer:
    """DNP3 TCP server that responds to master READ requests."""

    def __init__(self, addr: int = 10, port: int = 20000):
        self.addr = addr
        self.port = port
        self.sim = MeterStationSimulator()
        self._running = False

    def _build_response(self, src_addr: int, dst_addr: int, req_data: bytes, seq: int) -> bytes:
        """Build a DNP3 RESPONSE frame based on the request."""
        # Application layer
        app_ctrl = 0xC0 | (seq & 0x0F)  # FIR=1, FIN=1, SEQ

        # IIN bytes (all normal)
        iin1 = 0x00
        iin2 = 0x00

        app_data = bytes([app_ctrl, FUNC_RESPONSE, iin1, iin2])

        # Parse request to determine what to return
        if len(req_data) >= 3:
            req_group = req_data[0]
            req_data[1]
            req_qual = req_data[2]

            if req_group == GROUP_CLASS_0:
                # Return all data
                app_data += self._encode_analogs(0, 19)
                app_data += self._encode_binaries(0, 9)
                app_data += self._encode_counters(0, 3)

            elif req_group == GROUP_ANALOG_INPUT:
                start, stop = self._parse_range(req_data, req_qual)
                app_data += self._encode_analogs(start, stop)

            elif req_group == GROUP_BINARY_INPUT:
                start, stop = self._parse_range(req_data, req_qual)
                app_data += self._encode_binaries(start, stop)

            elif req_group == GROUP_COUNTER:
                start, stop = self._parse_range(req_data, req_qual)
                app_data += self._encode_counters(start, stop)

        # Build frame
        transport = bytes([0xC0])
        payload = transport + app_data

        length = len(payload) + 5
        # Control: DIR=0 (outstation->master), PRM=0
        ctrl = 0x44

        header = struct.pack("<HBBHH", DNP3_START, length, ctrl, dst_addr, src_addr)
        header_crc = struct.pack("<H", _crc16(header))

        frame = header + header_crc
        i = 0
        while i < len(payload):
            block = payload[i:i + 16]
            frame += block + struct.pack("<H", _crc16(block))
            i += 16

        return frame

    def _parse_range(self, req_data: bytes, qual: int) -> tuple[int, int]:
        """Extract start/stop range from request."""
        if qual == QUAL_ALL_POINTS:
            return 0, 19
        elif qual == QUAL_RANGE_8BIT:
            if len(req_data) >= 5:
                return req_data[3], req_data[4]
        elif qual == QUAL_RANGE_16BIT:
            if len(req_data) >= 7:
                start = struct.unpack("<H", req_data[3:5])[0]
                stop = struct.unpack("<H", req_data[5:7])[0]
                return start, stop
        return 0, 19

    def _encode_analogs(self, start: int, stop: int) -> bytes:
        """Encode analog inputs as Group 30 Var 5 (float with flag)."""
        values = self.sim.get_analogs()
        # Object header: Group 30, Var 5, Qualifier 0x00 (8-bit range)
        data = struct.pack("BBBBB", 30, 5, QUAL_RANGE_8BIT, start, stop)
        for idx in range(start, stop + 1):
            val = values.get(idx, 0.0)
            flag = 0x01  # ONLINE
            data += struct.pack("<Bf", flag, val)
        return data

    def _encode_binaries(self, start: int, stop: int) -> bytes:
        """Encode binary inputs as Group 1 Var 2 (with flag)."""
        values = self.sim.get_binaries()
        data = struct.pack("BBBBB", 1, 2, QUAL_RANGE_8BIT, start, stop)
        for idx in range(start, stop + 1):
            val = values.get(idx, False)
            flag = 0x01 | (0x80 if val else 0x00)  # ONLINE + STATE
            data += bytes([flag])
        return data

    def _encode_counters(self, start: int, stop: int) -> bytes:
        """Encode counters as Group 20 Var 1 (32-bit with flag)."""
        values = self.sim.get_counters()
        data = struct.pack("BBBBB", 20, 1, QUAL_RANGE_8BIT, start, stop)
        for idx in range(start, stop + 1):
            val = values.get(idx, 0)
            flag = 0x01  # ONLINE
            data += struct.pack("<BI", flag, val & 0xFFFFFFFF)
        return data

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming DNP3 master connection."""
        addr = writer.get_extra_info("peername")
        print(f"[DNP3] Master connected from {addr}")

        try:
            while self._running:
                data = await asyncio.wait_for(reader.read(4096), timeout=60.0)
                if not data:
                    break

                # Verify DNP3 start bytes
                if len(data) < 10:
                    continue
                start = struct.unpack("<H", data[0:2])[0]
                if start != DNP3_START:
                    continue

                # Parse header
                length = data[2]
                data[3]
                dst_addr = struct.unpack("<H", data[4:6])[0]
                src_addr = struct.unpack("<H", data[6:8])[0]

                # Verify this is addressed to us
                if dst_addr != self.addr:
                    continue

                # Extract payload (strip CRCs)
                payload = bytearray()
                pos = 10
                remaining = length - 5
                while remaining > 0 and pos < len(data):
                    block_size = min(16, remaining)
                    if pos + block_size > len(data):
                        break
                    payload.extend(data[pos:pos + block_size])
                    pos += block_size + 2
                    remaining -= block_size

                if len(payload) < 3:
                    continue

                payload[0]
                app_ctrl = payload[1]
                func_code = payload[2]
                seq = app_ctrl & 0x0F

                if func_code == FUNC_READ:
                    # Extract the object request (after func code)
                    req_data = bytes(payload[3:])

                    response = self._build_response(
                        src_addr=self.addr,
                        dst_addr=src_addr,
                        req_data=req_data,
                        seq=seq,
                    )
                    writer.write(response)
                    await writer.drain()

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"[DNP3] Client error: {e}")
        finally:
            writer.close()
            print(f"[DNP3] Master disconnected: {addr}")

    async def start(self):
        """Start the DNP3 outstation server."""
        self._running = True
        server = await asyncio.start_server(
            self.handle_client, "0.0.0.0", self.port
        )
        print(f"[DNP3] Outstation simulator running on port {self.port}, address {self.addr}")
        print("[DNP3] Simulating: Gas Pipeline Meter Station (EFM)")
        print("[DNP3]   Analog Inputs:  20 points (pressures, temps, flow, gas quality)")
        print("[DNP3]   Binary Inputs:  10 points (valve status, alarms, ESD)")
        print("[DNP3]   Counters:        4 points (volumes, comm stats)")

        async with server:
            await server.serve_forever()


async def main():
    parser = argparse.ArgumentParser(description="DNP3 Outstation Simulator")
    parser.add_argument("--port", type=int, default=20000, help="TCP port (default: 20000)")
    parser.add_argument("--addr", type=int, default=10, help="Outstation address (default: 10)")
    args = parser.parse_args()

    outstation = DNP3OutstationServer(addr=args.addr, port=args.port)
    await outstation.start()


if __name__ == "__main__":
    asyncio.run(main())
