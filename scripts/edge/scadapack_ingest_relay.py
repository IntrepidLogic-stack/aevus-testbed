#!/usr/bin/env python3
"""Edge-Pi SCADAPack 470 Modbus->/ingest relay (Task #134/#198).
Polls 192.168.88.21:502 comms-health and POSTs to Aevus /ingest, which the
deployed relay-overlay surfaces on the EFM/RTU pearl. READ-ONLY (IL-009/P-008).
"""

import json
import sys
import time
import urllib.request

from pymodbus.client import ModbusTcpClient

IP = "192.168.88.21"
PORT = 502
UNIT = 1
ASSET = "RTU-01"
INGEST = "https://aevus.intrepidlogic.io/api/v1/ingest"
INTERVAL = 30
WIN = []


def poll():
    c = ModbusTcpClient(IP, port=PORT, timeout=3)
    t0 = time.time()
    ok = False
    try:
        if c.connect():
            try:
                r = c.read_holding_registers(0, count=8, device_id=UNIT)
            except TypeError:
                r = c.read_holding_registers(0, count=8, slave=UNIT)
            ok = not r.isError()
    except Exception:
        ok = False
    finally:
        c.close()
    return ok, int((time.time() - t0) * 1000)


def comm_pct(ok):
    WIN.append(1 if ok else 0)
    if len(WIN) > 20:
        WIN.pop(0)
    return int(round(100 * sum(WIN) / max(1, len(WIN))))


def cycle():
    ok, ms = poll()
    pct = comm_pct(ok)
    if ok:
        vitals = {
            "MODBUS LINK": {"value": 1, "unit": "", "status": "good"},
            "MODBUS LATENCY": {"value": ms, "unit": "ms", "status": "good"},
            "COMM SUCCESS": {"value": pct, "unit": "%", "status": "good" if pct >= 90 else "warn"},
        }
    else:
        vitals = {
            "MODBUS LINK": {"value": 0, "unit": "", "status": "bad"},
            "COMMUNICATION FAULT ALARM": "ACTIVE",
            "COMM SUCCESS": {"value": pct, "unit": "%", "status": "bad"},
        }
    body = json.dumps({"asset_id": ASSET, "vitals": vitals}).encode()
    req = urllib.request.Request(INGEST, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(
                "poll",
                ("OK" if ok else "FAIL"),
                "lat",
                ms,
                "comm",
                pct,
                "| ingest",
                resp.status,
                resp.read().decode()[:160],
            )
            return True
    except Exception as e:
        print("ingest FAIL:", e)
        return False


if __name__ == "__main__":
    if "--once" in sys.argv:
        cycle()
        sys.exit(0)
    while True:
        try:
            cycle()
        except Exception as e:
            print("cycle err", e)
        time.sleep(INTERVAL)
