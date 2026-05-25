#!/usr/bin/env python3
"""
Aevus Demo Seed — Reset to demo-ready state with mixed health statuses.
Usage: python3 scripts/demo_seed.py [--mixed]

--mixed: Set 2 assets to warning/critical for alarm workflow demo
Default: All assets healthy (for clean demo)
"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.environ.get("AEVUS_DB", "/home/ubuntu/aevus-testbed/data/aevus.db")

ASSETS = [
    {"id": "EDGE-01", "name": "Raspberry Pi", "type": "router", "status": "good", "health": 91,
     "vendor": "Raspberry Pi Foundation", "model": "Pi 5", "protocol": "snmp",
     "ip_address": "192.168.88.254", "latitude": 29.3905, "longitude": -95.8401},
    {"id": "EFM-01", "name": "TotalFlow XFC G4", "type": "rtu", "status": "good", "health": 91,
     "vendor": "ABB", "model": "TotalFlow XFC G4", "protocol": "dnp3",
     "ip_address": "127.0.0.1", "latitude": 29.3904, "longitude": -95.8398},
    {"id": "RAD-01", "name": "Trio JR900 #1", "type": "radio", "status": "good", "health": 91,
     "vendor": "Trio", "model": "JR900", "protocol": "snmp",
     "ip_address": "192.168.88.11", "latitude": 29.3903, "longitude": -95.8395},
    {"id": "RAD-02", "name": "Trio JR900 #2", "type": "radio", "status": "good", "health": 91,
     "vendor": "Trio", "model": "JR900", "protocol": "snmp",
     "ip_address": "192.168.88.12", "latitude": 29.3906, "longitude": -95.8392},
    {"id": "RTR-01", "name": "MikroTik L009", "type": "router", "status": "good", "health": 91,
     "vendor": "MikroTik", "model": "L009UiGS-2HaxD-IN", "protocol": "snmp",
     "ip_address": "192.168.88.1", "latitude": 29.3902, "longitude": -95.8405},
    {"id": "RTU-01", "name": "SCADAPack 470", "type": "rtu", "status": "good", "health": 91,
     "vendor": "Schneider", "model": "SCADAPack 470", "protocol": "modbus",
     "ip_address": "127.0.0.1", "latitude": 29.3907, "longitude": -95.8400},
    {"id": "SW-01", "name": "Catalyst 2960", "type": "switch", "status": "good", "health": 91,
     "vendor": "Cisco", "model": "Catalyst 2960", "protocol": "snmp",
     "ip_address": "192.168.88.2", "latitude": 29.3901, "longitude": -95.8403},
]

MIXED_OVERRIDES = {
    "RTU-01": {"status": "warn", "health": 62},
    "RAD-02": {"status": "bad", "health": 28},
}

MIXED_ALARMS = [
    {"id": "ALM-DEMO-001", "severity": "critical", "asset_id": "RAD-02", "asset_name": "Trio JR900 #2",
     "message": "Signal quality degraded below threshold (28%)", "risk_score": 85,
     "detected_at": (datetime.utcnow() - timedelta(minutes=12)).isoformat(), "status": "open"},
    {"id": "ALM-DEMO-002", "severity": "warning", "asset_id": "RTU-01", "asset_name": "SCADAPack 470",
     "message": "Discharge pressure exceeding normal range (142 PSI)", "risk_score": 55,
     "detected_at": (datetime.utcnow() - timedelta(minutes=45)).isoformat(), "status": "open"},
    {"id": "ALM-DEMO-003", "severity": "warning", "asset_id": "RTU-01", "asset_name": "SCADAPack 470",
     "message": "Motor current elevated (112A, threshold 100A)", "risk_score": 40,
     "detected_at": (datetime.utcnow() - timedelta(hours=2)).isoformat(), "status": "acknowledged"},
]

def seed(mixed=False):
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    for asset in ASSETS:
        if mixed and asset["id"] in MIXED_OVERRIDES:
            asset.update(MIXED_OVERRIDES[asset["id"]])
        
        conn.execute("""
            UPDATE assets SET status=?, health=?, latitude=?, longitude=?
            WHERE id=?
        """, (asset["status"], asset["health"], asset["latitude"], asset["longitude"], asset["id"]))
    
    if mixed:
        # Insert demo alarms
        for alarm in MIXED_ALARMS:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO alarms (id, severity, asset_id, asset_name, message, risk_score, detected_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (alarm["id"], alarm["severity"], alarm["asset_id"], alarm["asset_name"],
                      alarm["message"], alarm["risk_score"], alarm["detected_at"], alarm["status"]))
            except Exception as e:
                print(f"  Alarm insert failed: {e}")
    
    conn.commit()
    conn.close()
    
    mode = "MIXED (2 degraded + 3 alarms)" if mixed else "CLEAN (all healthy)"
    print(f"\n  Aevus Demo Seed Applied — {mode}")
    print("  Site: Killdeer Field — 10102 Clydesdale Dr, Needville TX 77461")
    print(f"  Assets: {len(ASSETS)}")
    for a in ASSETS:
        status = a["status"]
        if mixed and a["id"] in MIXED_OVERRIDES:
            status = MIXED_OVERRIDES[a["id"]]["status"]
            health = MIXED_OVERRIDES[a["id"]]["health"]
        else:
            health = a["health"]
        icon = "●" if status == "good" else "▲" if status == "warn" else "✖"
        print(f"    {icon} {a['id']}: {a['name']} — {status} ({health}%)")
    if mixed:
        print(f"  Alarms: {len(MIXED_ALARMS)} demo alarms injected")
    print()

if __name__ == "__main__":
    mixed = "--mixed" in sys.argv
    seed(mixed)
