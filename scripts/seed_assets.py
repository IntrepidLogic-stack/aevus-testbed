#!/usr/bin/env python3
"""
Aevus Testbed — Seed Asset Registry

Populates the SQLite database with the 23-asset fleet inventory.
Run after discover_devices.py to confirm IPs, then run this to bootstrap the registry.

Usage:
    python scripts/seed_assets.py
    python scripts/seed_assets.py --reset   # wipe and re-seed
"""

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/aevus.db")

# ── 23-asset fleet registry ──
ASSETS = [
    # Compressor Station 1
    {"id": "PLC-CS1-101", "type": "plc",     "name": "PLC – Compressor 1",           "location": "Compressor Station 1", "vendor": "Allen-Bradley",     "model": "CompactLogix 5380", "firmware": "v32.011",  "ip": "10.0.2.21", "protocol": "ethernet_ip", "poll_interval": 1},
    {"id": "RAD-CS1-201", "type": "radio",   "name": "Radio – Compressor 1",         "location": "Compressor Station 1", "vendor": "Aviat",             "model": "SR+ 220MHz",        "firmware": "v8.4.2",   "ip": "10.0.1.11", "protocol": "snmp",        "poll_interval": 30},
    {"id": "SEN-CS1-301", "type": "sensor",  "name": "Sensor – Compressor 1 Pressure","location": "Compressor Station 1","vendor": "Emerson",           "model": "Rosemount 3051S",   "firmware": None,       "ip": None,         "protocol": "plc_proxy",   "poll_interval": 5},
    {"id": "PLC-CS1-102", "type": "plc",     "name": "PLC – Compressor 1 Aux",       "location": "Compressor Station 1", "vendor": "Allen-Bradley",     "model": "CompactLogix 5370", "firmware": "v30.014",  "ip": "10.0.2.22", "protocol": "ethernet_ip", "poll_interval": 1},

    # Tank Battery 5
    {"id": "SEN-TB5-301", "type": "sensor",  "name": "Sensor – Tank 1 Level",        "location": "Tank Battery 5",       "vendor": "Emerson",           "model": "Rosemount 5408",    "firmware": None,       "ip": None,         "protocol": "plc_proxy",   "poll_interval": 5},
    {"id": "SEN-TB5-302", "type": "sensor",  "name": "Sensor – Tank 2 Pressure",     "location": "Tank Battery 5",       "vendor": "Emerson",           "model": "Rosemount 3051S",   "firmware": None,       "ip": None,         "protocol": "plc_proxy",   "poll_interval": 5},
    {"id": "SEN-TB5-303", "type": "sensor",  "name": "Sensor – Tank 3 Pressure",     "location": "Tank Battery 5",       "vendor": "Emerson",           "model": "Rosemount 3051S",   "firmware": None,       "ip": None,         "protocol": "plc_proxy",   "poll_interval": 5},
    {"id": "GW-TB5-401",  "type": "gateway", "name": "Gateway – Tank Battery 5",     "location": "Tank Battery 5",       "vendor": "Cisco",             "model": "IR1101",            "firmware": "v17.9.4a", "ip": "10.0.3.31", "protocol": "snmp",        "poll_interval": 30},
    {"id": "PLC-TB5-101", "type": "plc",     "name": "PLC – Tank Battery 5",         "location": "Tank Battery 5",       "vendor": "Schneider Electric","model": "Modicon M340",      "firmware": "v3.10",    "ip": "10.0.2.25", "protocol": "modbus_tcp",  "poll_interval": 5},

    # Manifold
    {"id": "GW-MAN-401",  "type": "gateway", "name": "Gateway – Pipeline Manifold",  "location": "Manifold",             "vendor": "Cisco",             "model": "IR1101",            "firmware": "v17.9.4a", "ip": "10.0.3.32", "protocol": "snmp",        "poll_interval": 30},
    {"id": "SEN-MAN-301", "type": "sensor",  "name": "Sensor – Manifold Flow",       "location": "Manifold",             "vendor": "Micro Motion",      "model": "CMF200",            "firmware": None,       "ip": None,         "protocol": "plc_proxy",   "poll_interval": 5},

    # Water Injection 1
    {"id": "PLC-WI1-101", "type": "plc",     "name": "PLC – Water Injection 1",      "location": "Water Injection 1",    "vendor": "Schneider Electric","model": "Modicon M340",      "firmware": "v3.08",    "ip": "10.0.2.26", "protocol": "modbus_tcp",  "poll_interval": 5},
    {"id": "SEN-WI1-301", "type": "sensor",  "name": "Sensor – Injection Tank Level","location": "Water Injection 1",    "vendor": "Emerson",           "model": "Rosemount 5408",    "firmware": None,       "ip": None,         "protocol": "plc_proxy",   "poll_interval": 5},
    {"id": "GW-WI1-401",  "type": "gateway", "name": "Gateway – Water Injection 1",  "location": "Water Injection 1",    "vendor": "Cisco",             "model": "IR1101",            "firmware": "v17.9.4a", "ip": "10.0.3.33", "protocol": "snmp",        "poll_interval": 30},

    # Compressor Station 3
    {"id": "PLC-CS3-101", "type": "plc",     "name": "PLC – Compressor 2",           "location": "Compressor Station 3", "vendor": "Allen-Bradley",     "model": "CompactLogix 5380", "firmware": "v32.011",  "ip": "10.0.2.23", "protocol": "ethernet_ip", "poll_interval": 1},
    {"id": "PLC-CS3-102", "type": "plc",     "name": "PLC – Compressor 3",           "location": "Compressor Station 3", "vendor": "Allen-Bradley",     "model": "CompactLogix 5370", "firmware": "v30.014",  "ip": "10.0.2.24", "protocol": "ethernet_ip", "poll_interval": 1},
    {"id": "RAD-CS3-201", "type": "radio",   "name": "Radio – Compressor Stn 3",     "location": "Compressor Station 3", "vendor": "Aviat",             "model": "FNLT-M002",         "firmware": "v6.2.1",   "ip": "10.0.1.12", "protocol": "snmp",        "poll_interval": 30},
    {"id": "SEN-CS3-301", "type": "sensor",  "name": "Sensor – Compressor 3 Vibration","location":"Compressor Station 3","vendor": "SKF",               "model": "CMSS 2200",         "firmware": None,       "ip": None,         "protocol": "plc_proxy",   "poll_interval": 5},

    # Control Room
    {"id": "RAD-CR-201",  "type": "radio",   "name": "Radio – Control Room 2",       "location": "Control Room",         "vendor": "Aviat",             "model": "SR+ 220MHz",        "firmware": "v8.4.2",   "ip": "10.0.1.13", "protocol": "snmp",        "poll_interval": 30},
    {"id": "GW-CR-401",   "type": "gateway", "name": "Gateway – Control Room",       "location": "Control Room",         "vendor": "Cisco",             "model": "IR1101",            "firmware": "v17.9.4a", "ip": "10.0.3.34", "protocol": "snmp",        "poll_interval": 30},

    # Radio Tower A
    {"id": "RAD-RTA-201", "type": "radio",   "name": "Radio – Tower A Top",          "location": "Radio Tower A",        "vendor": "Aviat",             "model": "SR+ 220MHz",        "firmware": "v8.4.2",   "ip": "10.0.1.14", "protocol": "snmp",        "poll_interval": 30},
    {"id": "RAD-RTA-202", "type": "radio",   "name": "Radio – Tower A Mid",          "location": "Radio Tower A",        "vendor": "Aviat",             "model": "SR+ 220MHz",        "firmware": "v8.4.2",   "ip": "10.0.1.15", "protocol": "snmp",        "poll_interval": 30},
    {"id": "RAD-RTA-203", "type": "radio",   "name": "Radio – Tower A Base",         "location": "Radio Tower A",        "vendor": "Aviat",             "model": "SR+ 220MHz",        "firmware": "v8.4.2",   "ip": "10.0.1.16", "protocol": "snmp",        "poll_interval": 30},
]


def create_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK(type IN ('radio', 'plc', 'gateway', 'sensor')),
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            vendor TEXT NOT NULL,
            model TEXT NOT NULL,
            firmware TEXT,
            ip TEXT,
            protocol TEXT NOT NULL,
            poll_interval INTEGER NOT NULL DEFAULT 30,
            health INTEGER,
            status TEXT DEFAULT 'unknown',
            last_seen TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id TEXT PRIMARY KEY,
            severity TEXT NOT NULL CHECK(severity IN ('critical', 'warning', 'info')),
            asset_id TEXT NOT NULL REFERENCES assets(id),
            asset_name TEXT NOT NULL,
            message TEXT NOT NULL,
            risk_score INTEGER,
            detected_at TEXT NOT NULL,
            acknowledged_at TEXT,
            resolved_at TEXT,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'acknowledged', 'resolved'))
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT NOT NULL REFERENCES assets(id),
            severity TEXT NOT NULL CHECK(severity IN ('good', 'warn', 'bad', 'info')),
            message TEXT NOT NULL,
            timestamp TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_alerts_asset ON alerts(asset_id);
        CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
        CREATE INDEX IF NOT EXISTS idx_events_asset ON events(asset_id);
        CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);
    """)


def seed_assets(conn: sqlite3.Connection):
    now = datetime.now().isoformat()
    for a in ASSETS:
        conn.execute("""
            INSERT OR REPLACE INTO assets
                (id, type, name, location, vendor, model, firmware, ip, protocol, poll_interval, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unknown', ?, ?)
        """, (a["id"], a["type"], a["name"], a["location"], a["vendor"], a["model"],
              a["firmware"], a["ip"], a["protocol"], a["poll_interval"], now, now))
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Seed the Aevus asset registry")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables")
    args = parser.parse_args()

    DB_PATH.parent.mkdir(exist_ok=True)

    if args.reset and DB_PATH.exists():
        DB_PATH.unlink()
        print("  🗑  Deleted existing database")

    conn = sqlite3.connect(str(DB_PATH))
    create_tables(conn)
    seed_assets(conn)

    count = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    conn.close()

    print(f"  ✅ Seeded {count} assets into {DB_PATH}")
    print(f"     Radios:   {sum(1 for a in ASSETS if a['type'] == 'radio')}")
    print(f"     PLCs:     {sum(1 for a in ASSETS if a['type'] == 'plc')}")
    print(f"     Gateways: {sum(1 for a in ASSETS if a['type'] == 'gateway')}")
    print(f"     Sensors:  {sum(1 for a in ASSETS if a['type'] == 'sensor')}")


if __name__ == "__main__":
    main()
