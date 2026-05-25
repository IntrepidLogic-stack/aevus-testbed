#!/usr/bin/env python3
"""
Aevus Testbed — Device Discovery

SNMP walks the lab network subnets to discover reachable devices
and dump their available OIDs. Run this first to validate connectivity.

Usage:
    python scripts/discover_devices.py
    python scripts/discover_devices.py --subnet 10.0.1.0/24
    python scripts/discover_devices.py --host 10.0.1.11
"""

import argparse
import subprocess
import ipaddress
import json
import sys
from pathlib import Path
from datetime import datetime

# Lab subnets from .env defaults
DEFAULT_SUBNETS = {
    "radios":   "10.0.1.0/24",
    "plcs":     "10.0.2.0/24",
    "gateways": "10.0.3.0/24",
}
SNMP_COMMUNITY = "aevus_ro"

def snmp_walk(host: str, community: str = SNMP_COMMUNITY, timeout: int = 5) -> dict | None:
    """Run snmpwalk against a host, return parsed OID→value dict or None if unreachable."""
    try:
        result = subprocess.run(
            ["snmpwalk", "-v2c", "-c", community, "-t", str(timeout), host],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        
        oids = {}
        for line in result.stdout.strip().split("\n"):
            if "=" in line:
                parts = line.split("=", 1)
                oid = parts[0].strip()
                value = parts[1].strip() if len(parts) > 1 else ""
                oids[oid] = value
        return oids
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  ⚠  {host}: {e}")
        return None

def discover_subnet(subnet: str, label: str) -> list[dict]:
    """Scan a subnet, return list of discovered devices."""
    print(f"\n{'─' * 60}")
    print(f"Scanning {label}: {subnet}")
    print(f"{'─' * 60}")
    
    network = ipaddress.ip_network(subnet, strict=False)
    discovered = []
    
    for ip in network.hosts():
        host = str(ip)
        sys.stdout.write(f"  → {host}...")
        sys.stdout.flush()
        
        oids = snmp_walk(host, timeout=2)
        if oids is None:
            sys.stdout.write(" no response\n")
            continue
        
        # Extract sysDescr and sysName if available
        sys_descr = oids.get("SNMPv2-MIB::sysDescr.0", oids.get("iso.3.6.1.2.1.1.1.0", "unknown"))
        sys_name = oids.get("SNMPv2-MIB::sysName.0", oids.get("iso.3.6.1.2.1.1.5.0", "unknown"))
        
        device = {
            "ip": host,
            "sys_name": sys_name,
            "sys_descr": sys_descr,
            "oid_count": len(oids),
            "label": label,
            "discovered_at": datetime.now().isoformat(),
        }
        discovered.append(device)
        print(f" ✓ {sys_name} ({len(oids)} OIDs)")
    
    return discovered

def discover_host(host: str) -> dict | None:
    """Full SNMP walk of a single host, dump all OIDs."""
    print(f"\nFull SNMP walk: {host}")
    print(f"{'─' * 60}")
    
    oids = snmp_walk(host, timeout=10)
    if oids is None:
        print(f"  ✗ No response from {host}")
        return None
    
    print(f"  ✓ {len(oids)} OIDs discovered")
    for oid, value in sorted(oids.items()):
        print(f"    {oid} = {value}")
    
    return {"ip": host, "oids": oids}

def main():
    # `global` must appear before any reference to the name in the
    # function body (Python SyntaxError otherwise). The argparse
    # default below reads SNMP_COMMUNITY at parse-build time, so the
    # declaration has to come first.
    global SNMP_COMMUNITY

    parser = argparse.ArgumentParser(description="Aevus device discovery via SNMP")
    parser.add_argument("--subnet", help="Scan a specific subnet (e.g., 10.0.1.0/24)")
    parser.add_argument("--host", help="Full SNMP walk of a single host IP")
    parser.add_argument("--community", default=SNMP_COMMUNITY, help="SNMP community string")
    args = parser.parse_args()

    SNMP_COMMUNITY = args.community
    
    # Check snmpwalk is installed
    try:
        subprocess.run(["snmpwalk", "--version"], capture_output=True, timeout=5)
    except FileNotFoundError:
        print("ERROR: snmpwalk not found. Install net-snmp:")
        print("  macOS:  brew install net-snmp")
        print("  Ubuntu: sudo apt install snmp snmp-mibs-downloader")
        sys.exit(1)
    
    if args.host:
        result = discover_host(args.host)
        if result:
            out_path = Path("data") / f"oids_{args.host.replace('.', '_')}.json"
            out_path.parent.mkdir(exist_ok=True)
            out_path.write_text(json.dumps(result, indent=2))
            print(f"\n  Saved to {out_path}")
        return
    
    # Full subnet scan
    all_devices = []
    if args.subnet:
        all_devices = discover_subnet(args.subnet, "custom")
    else:
        for label, subnet in DEFAULT_SUBNETS.items():
            all_devices.extend(discover_subnet(subnet, label))
    
    # Summary
    print(f"\n{'═' * 60}")
    print(f"DISCOVERY COMPLETE: {len(all_devices)} devices found")
    print(f"{'═' * 60}")
    for d in all_devices:
        print(f"  {d['ip']:16s} {d['label']:12s} {d['sys_name']}")
    
    # Save results
    out_path = Path("data") / "discovered_devices.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(all_devices, indent=2))
    print(f"\nSaved to {out_path}")

if __name__ == "__main__":
    main()
