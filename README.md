# Aevus Real-Time Testbed

AI-powered SCADA intelligence platform — real-time telemetry ingestion from lab hardware.

**Intrepid Logic LLC** · SDVOSB · PREDICT. PREVENT. PERFORM.

## Quick Start

```bash
# 1. Clone and enter
cd aevus-testbed

# 2. Create virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your lab IPs and credentials

# 5. Discover lab devices
python scripts/discover_devices.py

# 6. Seed asset registry
python scripts/seed_assets.py

# 7. Start the platform
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 8. Open dashboard
# Browse to http://localhost:8000/dashboard
```

## Architecture

```
Lab Hardware → Collectors (SNMP/EtherNet-IP/Modbus)
    → Normalizer → InfluxDB (telemetry)
    → Health Scorer → SQLite (asset state)
    → Alert Engine → SQLite (alerts)
    → FastAPI REST + WebSocket → Dashboard HTML
```

## Lab Hardware

- 6× Aviat SR+ 220MHz / FNLT-M002 radios
- 8× Sierra Wireless RV50/RV50X/RV55 cellular modems  
- 6× Allen-Bradley CompactLogix / Schneider Modicon PLCs
- 4× Cisco IR1101 industrial gateways
- Cisco Catalyst 2960 switches · MikroTik L009 router · Uplogix 5000 OOB

## Safety

**IL-9000:** PLC firmware updates are never automated remotely. See CLAUDE.md for full constraint specification.

---
© 2026 Intrepid Logic LLC · SDVOSB · All rights reserved.
