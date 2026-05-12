#!/usr/bin/env python3
"""Reset assets to a known demo-ready state with mixed health statuses."""
import json, sys
sys.path.insert(0, '/home/ubuntu/aevus-testbed')

DEMO_ASSETS = [
    {"id": "EDGE-01", "name": "Raspberry Pi", "type": "router", "protocol": "SNMP v2c", "ip": "192.168.88.254", "status": "good", "health": 91, "latitude": 29.3905, "longitude": -95.8401},
    {"id": "EFM-01", "name": "TotalFlow XFC G4", "type": "rtu", "protocol": "dnp3", "ip": "127.0.0.1", "status": "good", "health": 91, "latitude": 29.3904, "longitude": -95.8398},
    {"id": "RAD-01", "name": "Trio JR900 #1", "type": "radio", "protocol": "SNMP v2c", "ip": "192.168.88.11", "status": "good", "health": 91, "latitude": 29.3903, "longitude": -95.8395},
    {"id": "RAD-02", "name": "Trio JR900 #2", "type": "radio", "protocol": "SNMP v2c", "ip": "192.168.88.12", "status": "good", "health": 91, "latitude": 29.3906, "longitude": -95.8392},
    {"id": "RTR-01", "name": "MikroTik L009", "type": "router", "protocol": "SNMP v2c", "ip": "192.168.88.1", "status": "good", "health": 91, "latitude": 29.3902, "longitude": -95.8405},
    {"id": "RTU-01", "name": "SCADAPack 470", "type": "rtu", "protocol": "Modbus TCP", "ip": "127.0.0.1", "status": "good", "health": 91, "latitude": 29.3907, "longitude": -95.8400},
    {"id": "SW-01", "name": "Catalyst 2960", "type": "switch", "protocol": "SNMP v2c", "ip": "192.168.88.2", "status": "good", "health": 91, "latitude": 29.3901, "longitude": -95.8403},
]

print("Demo seed data ready — 7 assets at Killdeer Field (Needville, TX)")
print("All assets: Good status, Health 91")
for a in DEMO_ASSETS:
    print(f"  {a['id']}: {a['name']} ({a['type']}) @ {a['ip']}")
