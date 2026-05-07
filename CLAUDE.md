# CLAUDE.md — Aevus Real-Time Testbed

## Project Identity

**Product:** Aevus — AI-powered SCADA intelligence platform for midstream oil & gas
**Company:** Intrepid Logic LLC (SDVOSB)
**Owner:** Woody (founder)
**Status:** Pre-revenue, building testbed against physical lab hardware
**Goal:** Wire live telemetry from lab equipment into the Aevus dashboard prototype, replacing static demo data with real SNMP/Modbus/DNP3 feeds

## Tech Stack (Decided)

- **Backend:** Python 3.11+ with FastAPI (async, WebSocket support, auto OpenAPI docs)
- **SNMP polling:** pysnmp / easysnmp (for Trio JR900 radios, MikroTik, Cisco Catalyst)
- **Modbus:** pymodbus (for SCADAPack 470 — Modbus TCP on port 502)
- **DNP3:** pydnp3 / dnp3-python (for SCADAPack 470 — DNP3 outstation address 10, TCP 20000)
- **Time-series DB:** InfluxDB 2.x (bucket: `aevus_telemetry`, org: `intrepid-logic`)
- **Relational DB:** SQLite for asset registry, alert log, config (upgrade to PostgreSQL later)
- **Real-time push:** WebSocket via FastAPI (dashboard connects on load, receives push updates)
- **Dashboard:** Single-file HTML (exists at `dashboard/Aevus_Console.html`) — modify its JS to fetch from the API instead of hardcoded arrays
- **Task scheduling:** APScheduler (polling loops at configurable intervals per equipment type)
- **ML/prediction:** scikit-learn for initial anomaly detection; upgrade path to PyTorch
- **Config:** `.env` file via python-dotenv; all secrets in `.env`, never committed
- **Edge collector:** Raspberry Pi (hostname: `aevus-edge`) on the lab LAN

## Directory Structure

```
aevus-testbed/
├── CLAUDE.md                    ← you are here
├── README.md
├── .env                         ← secrets (gitignored)
├── .env.example                 ← template
├── requirements.txt
├── pyproject.toml
│
├── src/
│   ├── __init__.py
│   ├── main.py                  ← FastAPI app entry point
│   ├── config.py                ← Settings from .env
│   │
│   ├── models/                  ← Pydantic models (asset, alert, prediction, vital)
│   │   ├── __init__.py
│   │   ├── asset.py
│   │   ├── alert.py
│   │   ├── prediction.py
│   │   └── telemetry.py
│   │
│   ├── collectors/              ← Equipment-specific polling modules
│   │   ├── __init__.py
│   │   ├── base.py              ← Abstract collector interface
│   │   ├── snmp_radio.py        ← Trio JR900 radios via SNMP v2c
│   │   ├── snmp_switch.py       ← Cisco Catalyst 2960 via SNMP
│   │   ├── snmp_router.py       ← MikroTik L009 via SNMP
│   │   ├── modbus_rtu.py        ← SCADAPack 470 via Modbus TCP
│   │   ├── dnp3_outstation.py   ← SCADAPack 470 via DNP3 TCP
│   │   └── sensor_proxy.py      ← Sensors polled through RTU, not direct
│   │
│   ├── engine/                  ← Processing pipeline
│   │   ├── __init__.py
│   │   ├── health_score.py      ← Composite health computation (see formula below)
│   │   ├── alert_engine.py      ← Threshold monitoring → alert generation
│   │   ├── prediction.py        ← Time-series anomaly detection
│   │   └── normalizer.py        ← Raw telemetry → normalized asset vitals
│   │
│   ├── storage/                 ← Database layer
│   │   ├── __init__.py
│   │   ├── influx.py            ← InfluxDB client (telemetry writes/queries)
│   │   ├── sqlite_db.py         ← Asset registry, alerts, config
│   │   └── migrations/
│   │
│   ├── api/                     ← FastAPI routes
│   │   ├── __init__.py
│   │   ├── assets.py            ← GET /assets, GET /assets/{id}
│   │   ├── alerts.py            ← GET /alerts, POST /alerts/{id}/acknowledge
│   │   ├── health.py            ← GET /health/summary, GET /health/trend
│   │   ├── diagnostics.py       ← GET /diagnostics/fleet, GET /diagnostics/signals
│   │   ├── predictions.py       ← GET /predictions
│   │   └── ws.py                ← WebSocket endpoint for real-time push
│   │
│   └── scheduler.py             ← APScheduler job setup (polling intervals)
│
├── dashboard/
│   ├── Aevus_Console.html       ← Existing prototype (to be wired to API)
│   └── api-client.js            ← JS module: fetch + WebSocket client
│
├── tests/
│   ├── test_collectors.py
│   ├── test_health_score.py
│   ├── test_alert_engine.py
│   └── test_api.py
│
├── scripts/
│   ├── discover_devices.py      ← SNMP walk to find all devices on the lab network
│   ├── seed_assets.py           ← Populate SQLite asset registry from lab inventory
│   └── simulate_telemetry.py    ← Generate fake telemetry for testing without hardware
│
└── docs/
    ├── BRAND_SYSTEM_v2.md
    └── TESTBED_HANDOFF.md       ← Full context from the collateral conversation
```

## HARD SAFETY RULE — IL-009

**PLC/RTU firmware updates are NEVER automated remotely.**

The platform can: track firmware versions, stage updates, verify signatures, schedule change windows, prepare rollback artifacts, report compliance.

The platform CANNOT: execute the final firmware write. That requires a credentialed technician physically on site.

This is enforced by code (not policy). Any function that touches PLC/RTU firmware must include an IL-009 interlock check. The interlock is a boolean constant `IL_009_ENFORCED = True` that is never set to False anywhere in the codebase. Any code review that attempts to bypass this should be flagged.

This is patentable invention P-008.

## Equipment Fleet (Actual Lab Hardware)

### Network Infrastructure

| Device | Vendor | Model | IP (interim) | Role | Status |
|---|---|---|---|---|---|
| Router | MikroTik | L009UiGS-2HaxD-IN | 192.168.88.1 | WAN edge, DHCP, NAT, SNMP | ✅ Configured |
| L2 Switch | Cisco | Catalyst 2960 | 192.168.88.2 (pending) | Port switching, future VLANs | ⏳ Needs console config |
| OOB Mgmt | Uplogix | 5000 | 192.168.88.5 (pending) | Out-of-band console access | ⏳ Needs console config |
| Edge Collector | Raspberry Pi | (TBD model) | 192.168.88.252 (DHCP) | Python collectors, SNMP tools | ⏳ Needs SSH enabled |
| Windows PC | — | SHOP-01 | 192.168.88.253 (DHCP) | RustDesk access, WinBox, config | ✅ Online |

### Radios — Trio JR900 (polled via SNMP v2c)

| Asset ID | Name | IP (interim) | SNMP Community | Polling | Status |
|---|---|---|---|---|---|
| RAD-01 | Trio JR900 #1 | 192.168.88.11 (pending) | aevus_ro | 30s | ⏳ Visible at L2 (MAC 00:1F:EB), needs serial config |
| RAD-02 | Trio JR900 #2 | 192.168.88.12 (pending) | aevus_ro | 30s | ⏳ Not yet visible on network |

**Trio JR900 SNMP OIDs** (enterprise OID: `1.3.6.1.4.1.5727`):

| Metric | OID | Unit | Notes |
|---|---|---|---|
| RSSI | `1.3.6.1.4.1.5727.1.1.1.0` | dBm | Received signal strength |
| SNR | `1.3.6.1.4.1.5727.1.1.2.0` | dB | Signal-to-noise ratio |
| Tx Power | `1.3.6.1.4.1.5727.1.2.1.0` | dBm | Transmit power |
| Modulation | `1.3.6.1.4.1.5727.1.2.2.0` | — | Current modulation scheme |
| Rx Packets | `1.3.6.1.4.1.5727.1.3.1.0` | count | Received packet counter |
| Tx Packets | `1.3.6.1.4.1.5727.1.3.2.0` | count | Transmitted packet counter |
| Error Packets | `1.3.6.1.4.1.5727.1.3.3.0` | count | Error packet counter |
| Temperature | `1.3.6.1.4.1.5727.1.4.1.0` | °C | Internal temperature |
| Voltage | `1.3.6.1.4.1.5727.1.4.2.0` | V | Supply voltage |

**First task after serial config: run `snmpwalk -v2c -c aevus_ro 192.168.88.11` to confirm OIDs.**

### RTU — SCADAPack 470 (polled via Modbus TCP + DNP3)

| Asset ID | Name | IP (interim) | Protocols | Polling | Status |
|---|---|---|---|---|---|
| RTU-01 | SCADAPack 470 | 192.168.88.21 (pending) | Modbus TCP :502, DNP3 :20000 | 5s | ⏳ Not yet visible on network |

**SCADAPack 470 Modbus TCP Register Map:**

| Register | Address | Type | Description | Unit |
|---|---|---|---|---|
| Suction Pressure | 40001 | Float32 | Compressor suction pressure | PSI |
| Discharge Pressure | 40003 | Float32 | Compressor discharge pressure | PSI |
| Flow Rate | 40005 | Float32 | Gas flow rate | MCFD |
| Gas Temperature | 40007 | Float32 | Process gas temperature | °F |
| Ambient Temperature | 40009 | Float32 | Ambient temperature | °F |
| Battery Voltage | 40011 | Float32 | RTU battery voltage | VDC |
| Solar Voltage | 40013 | Float32 | Solar panel voltage | VDC |
| Tank Level | 40015 | Float32 | Liquid tank level | Inches |
| Vibration | 40017 | Float32 | Equipment vibration | mm/s |
| Run Hours | 40019 | UInt32 | Equipment run hours | Hours |

**SCADAPack 470 Modbus Discrete Inputs:**

| Input | Address | Description |
|---|---|---|
| Compressor Running | 10001 | Compressor run status |
| High Pressure Alarm | 10002 | High pressure shutdown |
| Low Battery Alarm | 10003 | Battery below threshold |
| Communication Fault | 10004 | Comm link status |

**SCADAPack 470 DNP3 Configuration:**
- Outstation address: 10
- TCP port: 20000
- Master address: 1 (Aevus collector)
- Binary inputs: mapped to discrete alarms
- Analog inputs: mapped to process values
- Unsolicited responses: enabled

**pymodbus example:**
```python
from pymodbus.client import ModbusTcpClient
client = ModbusTcpClient('192.168.88.21', port=502)
client.connect()
# Read suction + discharge pressure (2 x Float32 = 4 registers)
result = client.read_holding_registers(40001, 4, slave=1)
# Decode Float32 from register pairs
import struct
suction_psi = struct.unpack('>f', struct.pack('>HH', result.registers[0], result.registers[1]))[0]
discharge_psi = struct.unpack('>f', struct.pack('>HH', result.registers[2], result.registers[3]))[0]
```

### MikroTik L009 (polled via SNMP v2c)

Already configured with SNMP enabled, community `aevus_ro`.

**Standard MIB OIDs:**
- sysDescr: `.1.3.6.1.2.1.1.1.0`
- sysName: `.1.3.6.1.2.1.1.5.0`
- ifOperStatus: `.1.3.6.1.2.1.2.2.1.8`
- ifInOctets: `.1.3.6.1.2.1.2.2.1.10`
- ifOutOctets: `.1.3.6.1.2.1.2.2.1.16`

### Cisco Catalyst 2960 (polled via SNMP — after console config)

**Standard + Cisco-specific OIDs:**
- ifOperStatus: `.1.3.6.1.2.1.2.2.1.8`
- ifInOctets: `.1.3.6.1.2.1.2.2.1.10`
- ifOutOctets: `.1.3.6.1.2.1.2.2.1.16`
- cpmCPUTotal5minRev: `.1.3.6.1.4.1.9.9.109.1.1.1.1.8`
- ciscoMemoryPoolUsed: `.1.3.6.1.4.1.9.9.48.1.1.1.5`

### Lab Network Topology (Current — Flat Interim)

```
Internet (Spectrum cable)
    │
    ▼
[MikroTik L009] ─── ether1 = WAN (DHCP client)
    │                 bridgeLocal = 192.168.88.1/24 (DHCP server)
    │
    ├── ether3 → SHOP-01 (Windows PC, 192.168.88.253)
    ├── ether4 → Trio JR900 #1 (L2 only, no IP yet)
    ├── ether5 → Cisco Catalyst 2960 (L2 only, no mgmt IP yet)
    │               │
    │               ├── (switchports) → Trio JR900 #2, SCADAPack 470,
    │               │                    Uplogix 5000 (not yet confirmed)
    │               └── (switchport) → Raspberry Pi (192.168.88.252)
    │
    └── Other ether ports → available
```

**Target architecture (post site-visit):** Migrate to VLANed 10.50.x.0/24:
- VLAN 10 (10.50.10.0/24) — Management
- VLAN 20 (10.50.20.0/24) — OT (radios, RTU)
- VLAN 30 (10.50.30.0/24) — Aevus (collector, dashboard)

This requires configuring both MikroTik (inter-VLAN routing) and Catalyst 2960 (port VLAN assignments) via console cables.

## Data Models (Pydantic)

```python
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime

class VitalSign(BaseModel):
    label: str          # e.g. "RSSI", "SUCTION PRESSURE"
    value: str          # e.g. "-68 dBm", "245.3 PSI"
    raw_value: float    # numeric for computation
    unit: str           # "dBm", "PSI", "MCFD", "%"
    status: Literal["good", "warn", "bad", ""] = ""

class AssetEvent(BaseModel):
    timestamp: datetime
    severity: Literal["good", "warn", "bad", "info"]
    message: str

class Asset(BaseModel):
    id: str             # "RAD-01", "RTU-01"
    type: Literal["radio", "rtu", "switch", "router", "sensor"]
    status: Literal["good", "warn", "bad", "unknown", "offline"]
    name: str           # "Trio JR900 #1"
    location: str       # "Lab Cabinet"
    health: Optional[int]  # 0-100, None if unknown
    last_seen: datetime
    vendor: str
    model: str
    firmware: Optional[str] = None
    vitals: list[VitalSign]
    events: list[AssetEvent]

class Alert(BaseModel):
    id: str
    severity: Literal["critical", "warning", "info"]
    asset_id: str
    asset_name: str
    message: str
    risk_score: Optional[int]  # 0-100
    detected_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    status: Literal["open", "acknowledged", "resolved"]

class Prediction(BaseModel):
    asset_id: str
    asset_name: str
    asset_type: str
    location: str
    risk_score: int      # 0-100
    estimated_failure: str  # "3 days"
    confidence_interval: str  # "2-5 days"
    primary_drivers: list[str]
```

## Health Score Formula

```python
def compute_health(asset: Asset) -> int:
    """
    Composite score 0-100.
    Weights:
      - Communication reliability: 35%
      - Vital-sign compliance: 30%
      - Predictive risk inversion: 20%
      - Maintenance currency: 15%

    Status assignment:
      80-100 → good (Healthy)
      50-79  → warn (Warning)
      1-49   → bad (Critical)
      0/None → unknown
    """
```

## Alert Thresholds (Defaults)

### Radio (Trio JR900)
| Metric | Warning | Critical |
|---|---|---|
| Health score | < 80 | < 50 |
| RSSI | < -80 dBm | < -90 dBm |
| SNR | < 15 dB | < 10 dB |
| Temperature | > 60°C | > 75°C |
| Error packet rate | > 1% | > 5% |

### RTU (SCADAPack 470)
| Metric | Warning | Critical |
|---|---|---|
| Battery voltage | < 12.0 VDC | < 11.5 VDC |
| Suction pressure | > 800 PSI | > 900 PSI |
| Discharge pressure | > 1200 PSI | > 1400 PSI |
| Vibration | > 4.5 mm/s | > 7.1 mm/s |
| Communication fault | — | active |

### Network (MikroTik, Catalyst)
| Metric | Warning | Critical |
|---|---|---|
| CPU load | > 70% | > 90% |
| Interface errors | > 100/min | > 1000/min |
| Link status | — | down |

## API Endpoints (FastAPI)

```
GET  /api/v1/assets                    → list all assets (filterable by type, status)
GET  /api/v1/assets/{id}               → single asset with full vitals + events
GET  /api/v1/health/summary            → overall health, per-class scores
GET  /api/v1/health/trend?days=30      → time-series health data
GET  /api/v1/alerts                    → list alerts (filterable by severity, status)
POST /api/v1/alerts/{id}/acknowledge   → acknowledge an alert
GET  /api/v1/diagnostics/fleet         → equipment fleet breakdown by vendor
GET  /api/v1/diagnostics/signals       → predictive signal trends per asset
GET  /api/v1/predictions               → predicted failures list
GET  /api/v1/reports                   → report metadata
GET  /api/v1/integrations              → connected system status
WS   /api/v1/ws                        → WebSocket: push asset updates, alerts, health changes
```

## Build Priority Order

**Phase 1 — Discovery & Ingestion (do first)**
1. `scripts/discover_devices.py` — SNMP walk all lab IPs, dump available OIDs
2. `scripts/seed_assets.py` — populate SQLite with the lab asset registry
3. `src/collectors/snmp_radio.py` — poll Trio JR900, parse RSSI/SNR/TxPower/Temp
4. `src/collectors/snmp_router.py` — poll MikroTik L009, parse interface stats
5. `src/collectors/modbus_rtu.py` — poll SCADAPack 470, parse process values
6. `src/storage/influx.py` — write raw telemetry to InfluxDB

**Phase 2 — Processing**
7. `src/engine/normalizer.py` — raw values → VitalSign objects with status tagging
8. `src/engine/health_score.py` — compute composite scores
9. `src/engine/alert_engine.py` — threshold checks → alert generation

**Phase 3 — API**
10. `src/api/assets.py` + `src/api/health.py` — basic REST endpoints
11. `src/api/ws.py` — WebSocket push
12. `src/main.py` — wire everything together with APScheduler

**Phase 4 — Dashboard Integration**
13. `dashboard/api-client.js` — replace hardcoded JS arrays with API fetch + WebSocket
14. Wire drilldown drawer to fetch live asset detail on click

**Phase 5 — Prediction & Expansion**
15. `src/engine/prediction.py` — time-series anomaly detection on RF + process metrics
16. `src/collectors/dnp3_outstation.py` — DNP3 polling of SCADAPack 470
17. `src/collectors/snmp_switch.py` — Cisco Catalyst 2960 after console config

## Coding Conventions

- Python 3.11+ with type hints everywhere
- Pydantic v2 for all data models
- async/await for all I/O (FastAPI, SNMP, DB)
- `ruff` for linting, `black` for formatting
- Tests in `tests/` using `pytest` + `pytest-asyncio`
- Logging via `structlog` (structured JSON logs)
- All config via `.env` — never hardcode IPs, credentials, or secrets
- Docstrings on every public function
- IL-009 interlock check on any function touching RTU/PLC firmware

## Brand Tokens (for dashboard CSS reference)

```css
--accent: #06B6D4;
--bg-app: #0B1020;
--bg-canvas: #0F1629;
--bg-card: #161E33;
--status-good: #10D478;
--status-warn: #FBBF24;
--status-bad: #EF4444;
--status-info: #60A5FA;
--status-unknown: #A78BFA;
```

Fonts: Manrope (display) + JetBrains Mono (numeric)

## Demo Fleet vs Lab Hardware

The dashboard prototype and TESTBED_HANDOFF.md reference a **modeled 23-asset demo fleet** (Aviat SR+ radios, Allen-Bradley PLCs, Cisco IR1101 gateways, Emerson/SKF sensors). That fleet represents a realistic midstream deployment for the pilot pitch.

The **actual lab hardware** is:
- 2× Trio JR900 radios (SNMP)
- 1× SCADAPack 470 RTU (Modbus TCP + DNP3)
- 1× Cisco Catalyst 2960 switch (SNMP)
- 1× MikroTik L009 router (SNMP)
- 1× Uplogix 5000 (console management)
- 1× Raspberry Pi (edge collector)

The testbed code must work against the real lab hardware. The dashboard can show both real lab assets and simulated demo assets (clearly labeled) for pitch purposes.
