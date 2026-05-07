# AEVUS — Real-Time Testbed Handoff

**Purpose:** This document transfers the complete context from the Aevus marketing/collateral build conversation into the real-time testbed integration conversation. It captures the brand system, data models, equipment fleet, integration architecture, safety constraints, dashboard contract, and lab hardware — everything needed to wire live data sources into the Aevus platform.

**Date:** May 5, 2026
**Owner:** Woody, Founder, Intrepid Logic LLC (SDVOSB)
**Status:** Pre-revenue. Pursuing first pilot engagement (target: Momentum Energy Midstream, Houston TX). All operational figures are modeled, not measured from a production deployment.

---

## 1. PRODUCT IDENTITY

**Product:** Aevus
**Tagline:** PREDICT. PREVENT. PERFORM.
**Company:** Intrepid Logic LLC (SDVOSB — Service-Disabled Veteran-Owned Small Business, co-founded with Woody's father, a 100% service-disabled Air Force veteran)
**What it is:** AI-powered SCADA intelligence platform for midstream oil and gas. Addresses RF network reliability, predictive equipment failure detection, gas measurement compliance, and firmware orchestration across heterogeneous industrial equipment fleets.

**v1 branding ("Aevus by SCADAX — Powered by Intrepid Logic") is fully retired.** All new work uses "Aevus" only. Intrepid Logic appears in footer/copyright only.

---

## 2. BRAND SYSTEM (v2 — CANONICAL)

### 2.1 Color Tokens

| Token | Hex | Semantic |
|---|---|---|
| `--accent` | `#06B6D4` | Primary brand, active states, CTA fills, primary chart series |
| `--accent-bright` | `#22D3EE` | Hover, focus, glow |
| `--accent-dim` | `#0E7490` | Pressed states |
| `--bg-app` | `#0B1020` | Deepest layer (sidebar) |
| `--bg-canvas` | `#0F1629` | Main content canvas |
| `--bg-card` | `#161E33` | Card / panel base |
| `--bg-elevated` | `#1E2742` | Hovered rows, popovers |
| `--bg-input` | `#1A2238` | Form inputs |
| `--text-primary` | `#FFFFFF` | Headlines, KPI values |
| `--text-secondary` | `#B4BCD0` | Body copy |
| `--text-muted` | `#7B8499` | Captions, labels |
| `--text-faint` | `#4A5168` | Disabled state |
| `--status-good` | `#10D478` | Healthy / online / success |
| `--status-warn` | `#FBBF24` | Warning / degradation |
| `--status-bad` | `#EF4444` | Critical / failure |
| `--status-info` | `#60A5FA` | Informational |
| `--status-unknown` | `#A78BFA` | Unknown / unclassified |
| `--status-offline` | `#6B7280` | Offline / no signal |

### 2.2 Typography

Display + body: **Manrope** (400, 500, 600, 700)
Mono / numeric: **JetBrains Mono** (400, 500, 600)
Office fallback: Calibri + Consolas

### 2.3 Layout

Persistent 240px left sidebar (`--bg-app`). Logo lock-up at top. Nine nav items: Overview, Assets, Health, Alerts, Diagnostics, Trends, Reports, Integrations, Settings. Main canvas `--bg-canvas` padded 24px. Cards `--bg-card`, 1px border, 12px radius.

---

## 3. EQUIPMENT FLEET (DEMO / PILOT SCOPE)

### 3.1 RF Radios

| Vendor | Model | Count | Freq | Notes |
|---|---|---|---|---|
| Aviat | SR+ 220MHz | 12 | 220 MHz | Primary narrowband fleet |
| Aviat | FNLT-M002 | 4 | varies | Fixed-link terminals |
| Sierra Wireless | RV50 / RV50X | 8 | LTE Cat-4 | Cellular modems |
| Sierra Wireless | RV55 5G | 3 | LTE/5G | Next-gen cellular, Phase 3 roadmap |
| Legacy | SD2 | 3 | varies | End-of-life, replacement scheduled Q2 |
| **Total** | | **30 sites** | | Enterprise model: 1,248 assets |

### 3.2 PLCs (Programmable Logic Controllers)

| Vendor | Model | Firmware | Typical Use |
|---|---|---|---|
| Allen-Bradley | CompactLogix 5380 | v32.011 | Primary compressor control |
| Allen-Bradley | CompactLogix 5370 | v30.014 | Auxiliary / legacy |
| Schneider Electric | Modicon M340 | v3.08–v3.10 | Water injection, tank battery |

### 3.3 Gateways

| Vendor | Model | Firmware | Role |
|---|---|---|---|
| Cisco | IR1101 | v17.9.4a | Industrial router / gateway, 64-connection pool |

### 3.4 Sensors

| Vendor | Model | Measurement |
|---|---|---|
| Emerson | Rosemount 3051S | Pressure (differential & absolute) |
| Emerson | Rosemount 5408 | Level (guided-wave radar) |
| Micro Motion | CMF200 | Flow (Coriolis) |
| SKF | CMSS 2200 | Vibration |

### 3.5 Facility Zones (Schematic)

Six zones in the demo schematic, interconnected by pipeline manifolds:

1. **Compressor Station 1** (top-left) — 2 PLCs, 1 radio, 1 sensor
2. **Tank Battery 5** (top-center) — 1 PLC, 3 sensors, 1 gateway
3. **Manifold** (center connections) — 1 gateway, 1 flow sensor
4. **Water Injection 1** (bottom-left) — 1 PLC, 1 sensor, 1 gateway
5. **Compressor Station 3** (bottom-center) — 2 PLCs, 1 radio, 1 vibration sensor
6. **Control Room** (bottom-right) — 1 radio, 1 gateway
7. **Radio Tower A** (right) — 3 radios (top/mid/base)

---

## 4. DATA MODEL — ASSET RECORD

Every asset in the fleet follows this schema. The dashboard drilldown drawer renders from this structure directly.

```json
{
  "id": "RAD-CR-201",
  "type": "radio | plc | gateway | sensor",
  "status": "good | warn | bad | unknown | offline",
  "name": "Radio – Control Room 2",
  "location": "Control Room",
  "health": 12,
  "lastSeen": "2m ago",
  "vendor": "Aviat",
  "model": "SR+ 220MHz",
  "firmware": "v8.4.2",
  "vitals": [
    { "label": "RSSI", "value": "-94 dBm", "status": "bad" },
    { "label": "SINR", "value": "6.2 dB", "status": "bad" },
    { "label": "BER", "value": "4.8e-5", "status": "bad" },
    { "label": "VSWR", "value": "2.41", "status": "bad" }
  ],
  "events": [
    { "time": "2m ago", "type": "bad", "message": "High failure probability detected (98% risk · 3 days)" },
    { "time": "6h ago", "type": "warn", "message": "VSWR exceeded — antenna degradation likely" },
    { "time": "18h ago", "type": "warn", "message": "RSSI degradation accelerating" }
  ]
}
```

### 4.1 Type-Specific Vital Signs

**Radio** vital signs: RSSI (dBm), SINR (dB), BER (scientific notation), VSWR (ratio), Frequency (MHz), Tx Power (dBm)

**PLC** vital signs: Cycle Time (ms), Scan Rate (Hz), Comm Health (%), CPU Load (%), Memory Util (%), I/O Status

**Gateway** vital signs: Buffer Utilization (%), Throughput (Mbps), Error Rate (%), Active Connections (n/max), Uptime

**Sensor** vital signs: Current Reading (units vary), Expected Range, Drift 30-day (%), Last Calibration (date), Sensor Type (pressure/level/flow/vibration/temp)

### 4.2 Health Score Computation (target for testbed)

Health score (0–100) is a composite of:
- Communication reliability (weight: 35%)
- Vital-sign compliance vs thresholds (weight: 30%)
- Predictive model risk score inversion (weight: 20%)
- Calibration/maintenance currency (weight: 15%)

Status assignment from health score:
- 80–100 → `good` (Healthy)
- 50–79 → `warn` (Warning)
- 1–49 → `bad` (Critical)
- 0 or null → `unknown`

### 4.3 Alert Model

```json
{
  "id": "ALERT-20260505-001",
  "severity": "critical | warning | info",
  "assetId": "RAD-CR-201",
  "assetName": "Radio – Control Room 2",
  "message": "High failure probability detected",
  "riskScore": 98,
  "detectedAt": "2026-05-05T10:22:38Z",
  "acknowledgedAt": null,
  "resolvedAt": null,
  "status": "open | acknowledged | resolved"
}
```

### 4.4 Prediction Model

```json
{
  "assetId": "RAD-CR-201",
  "assetName": "Radio – Control Room 2",
  "assetType": "radio",
  "location": "Control Room",
  "riskScore": 98,
  "estimatedFailure": "3 days",
  "confidenceInterval": "2–5 days",
  "primaryDrivers": ["VSWR degradation", "RSSI decline", "BER escalation"]
}
```

---

## 5. COMPLETE ASSET INVENTORY (23 DEMO ASSETS)

These are the 23 assets built into the dashboard prototype, each with realistic data. The testbed should wire real data sources to replace these static records.

### Compressor Station 1

| ID | Name | Type | Vendor · Model | Status | Health |
|---|---|---|---|---|---|
| PLC-CS1-101 | PLC – Compressor 1 | plc | Allen-Bradley · CompactLogix 5380 | good | 96 |
| RAD-CS1-201 | Radio – Compressor 1 | radio | Aviat · SR+ 220MHz | good | 94 |
| SEN-CS1-301 | Sensor – Compressor 1 Pressure | sensor | Emerson · Rosemount 3051S | good | 92 |
| PLC-CS1-102 | PLC – Compressor 1 Aux | plc | Allen-Bradley · CompactLogix 5370 | warn | 67 |

### Tank Battery 5

| ID | Name | Type | Vendor · Model | Status | Health |
|---|---|---|---|---|---|
| SEN-TB5-301 | Sensor – Tank 1 Level | sensor | Emerson · Rosemount 5408 | good | 91 |
| SEN-TB5-302 | Sensor – Tank 2 Pressure | sensor | Emerson · Rosemount 3051S | good | 94 |
| SEN-TB5-303 | Sensor – Tank 3 Pressure | sensor | Emerson · Rosemount 3051S | warn | 54 |
| GW-TB5-401 | Gateway – Tank Battery 5 | gateway | Cisco · IR1101 | warn | 51 |
| PLC-TB5-101 | PLC – Tank Battery 5 | plc | Schneider · Modicon M340 | warn | 42 |

### Manifold

| ID | Name | Type | Vendor · Model | Status | Health |
|---|---|---|---|---|---|
| GW-MAN-401 | Gateway – Pipeline Manifold | gateway | Cisco · IR1101 | good | 88 |
| SEN-MAN-301 | Sensor – Manifold Flow | sensor | Micro Motion · CMF200 | unknown | — |

### Water Injection 1

| ID | Name | Type | Vendor · Model | Status | Health |
|---|---|---|---|---|---|
| PLC-WI1-101 | PLC – Water Injection 1 | plc | Schneider · Modicon M340 | good | 78 |
| SEN-WI1-301 | Sensor – Injection Tank Level | sensor | Emerson · Rosemount 5408 | warn | 51 |
| GW-WI1-401 | Gateway – Water Injection 1 | gateway | Cisco · IR1101 | good | 92 |

### Compressor Station 3

| ID | Name | Type | Vendor · Model | Status | Health |
|---|---|---|---|---|---|
| PLC-CS3-101 | PLC – Compressor 2 | plc | Allen-Bradley · CompactLogix 5380 | good | 89 |
| PLC-CS3-102 | PLC – Compressor 3 | plc | Allen-Bradley · CompactLogix 5370 | **bad** | 28 |
| RAD-CS3-201 | Radio – Compressor Stn 3 | radio | Aviat · FNLT-M002 | good | 82 |
| SEN-CS3-301 | Sensor – Compressor 3 Vibration | sensor | SKF · CMSS 2200 | warn | 47 |

### Control Room

| ID | Name | Type | Vendor · Model | Status | Health |
|---|---|---|---|---|---|
| RAD-CR-201 | Radio – Control Room 2 | radio | Aviat · SR+ 220MHz | **bad** | 12 |
| GW-CR-401 | Gateway – Control Room | gateway | Cisco · IR1101 | good | 89 |

### Radio Tower A

| ID | Name | Type | Vendor · Model | Status | Health |
|---|---|---|---|---|---|
| RAD-RTA-201 | Radio – Tower A Top | radio | Aviat · SR+ 220MHz | good | 91 |
| RAD-RTA-202 | Radio – Tower A Mid | radio | Aviat · SR+ 220MHz | good | 88 |
| RAD-RTA-203 | Radio – Tower A Base | radio | Aviat · SR+ 220MHz | good | 93 |

---

## 6. DASHBOARD PAGE CONTRACTS

Each page in the Aevus dashboard expects specific data structures from the backend. This section defines what each page needs so the testbed can wire up the correct feeds.

### 6.1 Overview Page

Needs: KPI summary (assets monitored, health score, predicted failures, active alerts), active alerts list (top 4 by severity/recency), predicted failures table (top 5 by risk score), health trend chart (30-day time series), asset type distribution (counts by type), health breakdown by class (radio/plc/gateway/sensor scores), system status (ingestion, alerting, ML, database).

### 6.2 Assets Page

Needs: Full asset inventory with pagination/search/filter (by type, status, location). Each row: name, type, location, health score, last seen, status. Filter controls for Type (radio/plc/gateway/sensor), Status (good/warn/bad/unknown), Location (all zones).

### 6.3 Health Page

Needs: Overall health score, uptime (30d), predicted failures count, MTTR. Per-class health gauges (radio, plc, gateway, sensor — each 0–100). 90-day multi-line trend chart (overall + per-class). Top risk assets list (sorted by risk score descending).

### 6.4 Alerts Page

Needs: Open alert count, breakdown by severity (critical/warning/info), resolved count (24h). Full alert log with severity, asset, message, risk score, detected timestamp, status. Filterable by severity and status.

### 6.5 Diagnostics Page

Needs: Fleet-wide RF metrics (avg RSSI, avg SINR, avg BER). Equipment fleet breakdown by vendor (count, percentage, EOL status). Predictive signal trends (per-asset sparklines with predicted trajectory). Firmware compliance grid (per-vendor: total units, current count, staged count, pending auth count). IL-009 enforcement status (always engaged, non-disableable).

### 6.6 Trends Page

Needs: 90-day time series for message delivery rate, health score, MTTR, anomaly count. Per-metric trend cards with delta vs baseline. Multi-line chart with selectable time range (7d/30d/90d).

### 6.7 Reports Page

Needs: Report generation metadata (count, category breakdown). Recent reports list (name, type, generated timestamp, page count, file size, download link). Scheduled export list (name, frequency, next run, status). Compliance report references (AGA-3, API 21.1).

### 6.8 Integrations Page

Needs: Connected system registry (name, type, status, last sync, events/day). Target integrations: AVEVA System Platform (SCADA), OSIsoft PI (historian), Allen-Bradley Logix (PLC programming), Aviat ProVision (RF management), Sierra AirVantage (LTE/5G modem management), Splunk (log aggregation), ServiceNow (incident management), Microsoft Teams (alert notifications).

### 6.9 Settings Page

Needs: User profile (name, email, 2FA status). Notification preferences (per-severity channel routing). Alert threshold configuration (critical %, warning %, RSSI floor, predictive lead-time floor). IL-009 enforcement display (locked, non-disableable). API key management (count, last rotation). Audit log retention setting.

### 6.10 Asset Drilldown Drawer

Triggered by clicking any asset marker on the schematic map. Needs: Full asset record (schema in Section 4), including health gauge, equipment metadata, vital signs grid, recent activity timeline.

---

## 7. INTEGRATION ARCHITECTURE (TARGET)

### 7.1 Data Sources → Aevus

| Source | Protocol | Data Type | Frequency |
|---|---|---|---|
| AVEVA System Platform | OPC UA / proprietary | SCADA telemetry, HMI state | Real-time (1–5s) |
| OSIsoft PI Historian | PI Web API (REST) | Historical time-series | Batch (every 15–60s) |
| Allen-Bradley Logix | EtherNet/IP (CIP) | PLC telemetry, cycle-time, I/O | Real-time (100ms–1s) |
| Aviat ProVision | SNMP / REST API | Radio RF metrics (RSSI, SINR, BER, VSWR) | Polling (30s) |
| Sierra AirVantage | REST API / MQTT | Cellular modem status, signal, data usage | Polling (60s) |
| Modbus / serial | Modbus TCP/RTU | Legacy device data (SD2) | Polling (5–30s) |
| SNMP | SNMPv2c/v3 | Gateway/switch health | Polling (30s) |

### 7.2 Aevus → External Systems

| Destination | Protocol | Data Type | Trigger |
|---|---|---|---|
| Splunk | HEC (HTTP Event Collector) | Structured events, anomalies | On event |
| ServiceNow | REST API | Incident tickets, change requests | On alert |
| Microsoft Teams | Webhook | Alert notifications | On critical/warning |
| Email (SMTP) | SMTP | Scheduled reports, digest alerts | On schedule |

### 7.3 Internal Processing Pipeline

```
Data Ingestion → Normalization → Time-series Store → ML/Anomaly Detection → Health Scoring → Alert Engine → Dashboard API
```

The ML engine runs predictive models per asset type (equipment-specific behavior learning, per the roadmap Phase 02). The health scoring engine computes composite scores per Section 4.2.

---

## 8. SAFETY CONSTRAINTS

### 8.1 IL-009 Firmware Safety Interlock (HARD RULE)

**PLC firmware updates are NEVER automated remotely.** The Aevus platform orchestrates everything around this constraint:

- ✅ Firmware version tracking across the fleet
- ✅ Update staging and signature verification
- ✅ Change-window scheduling
- ✅ Rollback artifact preparation
- ✅ Compliance reporting
- ❌ **Remote execution of the final firmware write** — NEVER

The final write must be authorized by a credentialed technician physically on site. There is no override anywhere in the platform. This is enforced by platform interlock, not policy. The toggle in the Settings page is rendered as "locked" — visually present but functionally non-disableable.

This is a deliberate, **patentable distinction (P-008)** and must appear in any technical or sales material that touches firmware orchestration.

### 8.2 Pre-Revenue Honesty

All operational impact figures (message delivery 77→96.3%, MTTR 4.2→0.8h, $1.1M savings, etc.) are **modeled scenarios**, not measured from production deployments. The testbed should label its own measurements separately from these modeled baselines.

---

## 9. LAB / NETWORKING HARDWARE

Woody's physical lab includes:

| Equipment | Model | Role |
|---|---|---|
| Layer 2 switches | Cisco Catalyst 2960 | Network backbone |
| Out-of-band management | Uplogix 5000 | Remote console access |
| Router | MikroTik L009 | WAN edge, VLANs |
| Rack | 9U wall-mount | Physical housing |
| Target radios | Aviat SR+ 220MHz, FNLT-M002, Sierra RV50/RV50X/RV55 | RF fleet under test |
| Mapbox token | `pk.eyJ1Ijoid29vZHlpbCIsImEiOiJjbWR4eW5keTUwOTlvMmxxMXo1aGljdWdyIn0.f4ud1cQ6mf-oNM69iY6fEg` | Geographic map (if needed, not used in current schematic view) |

---

## 10. LOCKED FIGURES (PILOT MODELING)

These figures are used consistently across all collateral and dashboard demo data. The testbed should NOT modify these — instead, it should produce its own measured figures alongside.

### Operational
- Message delivery: 77% → 96.3% (modeled)
- Monthly outages: 18 → 3
- MTTR: 4.2h → 0.8h
- Annual loss before: $2.3M
- Modeled annual savings: $1.1M
- Year-1 investment: $325K
- Payback: 4.2 months
- 5-year net value: $5.2M+

### Gas Measurement
- Henry Hub: $3.50/MMBtu · Industrial: $4.21/MCF
- Per-meter monthly loss: $22,256
- Fleet exposure: $7.21M across 27 meters
- Compliance: 98.2% (AGA-3 99.4%, API 21.1 97.8%, Audit 96.1%, Calibration 88.5%)

### IP Portfolio
- 7 patents (P-001 to P-007; P-008 = IL-009)
- 5 trademarks (Aevus, Intrepid Logic, AI SCADA Engineer, PREDICT. PREVENT. PERFORM., +1 TBD)
- 7 copyrightable works
- Licensing potential: $3.5M–$11.5M/yr

### Roadmap
- Phase 01 Foundation (Y1): RF visibility, equipment telemetry, AGA-3/API 21.1, first pilot
- Phase 02 Predictive Scale (Y2): Equipment-specific learning, predictive maintenance, geo expansion
- Phase 03 5G Migration (Y3): RV55 5G, hybrid orchestration, edge intelligence
- Phase 04 Autonomous Ops (Y4-5): Closed-loop within IL-009, digital twin, manufacturer licensing

---

## 11. KEY COLLABORATORS

- **Greg Winter** — Contributed buyer-priority framework (ROI / Risk Reduction / Operational Efficiency) and structured collateral framework (2-pager + 10-section). Refined brand direction. All messaging should frame in Greg's three-lens approach.
- **Momentum Energy Midstream** (Houston, TX) — Pilot target. NOT a customer. NOT a signed engagement. All references must say "target" or "pursuit," never "customer" or "partner."

---

## 12. TESTBED INTEGRATION PRIORITIES

Suggested order for wiring the testbed to real data:

1. **SNMP polling of lab radios** (Aviat SR+, Sierra RV50) → feeds RSSI, SINR, BER, VSWR into the asset data model → replaces static vital-sign data in the dashboard
2. **EtherNet/IP polling of PLCs** (Allen-Bradley via L009 router) → feeds cycle time, scan rate, comm health → replaces PLC vital signs
3. **Health score computation** — implement the composite formula (Section 4.2) against real telemetry → replaces static health numbers
4. **Alert engine** — threshold monitoring against real data → generates real alerts → replaces static alert list
5. **Predictive model** — time-series anomaly detection on RF metrics → generates predicted failure estimates → replaces static predictions table
6. **Dashboard API** — REST/WebSocket endpoint that the HTML dashboard can poll → replaces the hardcoded JS data arrays

---

## 13. HOW TO USE THIS DOCUMENT

### Option A: Upload as Project Knowledge
In the "Real-time Testbed Integration" conversation, go to the project settings and add this file as project knowledge. The conversation will then have full context for every build decision.

### Option B: Paste the key sections
If the conversation doesn't use project knowledge, paste Sections 3 (Equipment Fleet), 4 (Data Model), 6 (Dashboard Page Contracts), 7 (Integration Architecture), 8 (Safety Constraints), and 9 (Lab Hardware) into the conversation's first message.

### Option C: Reference by name
If both conversations share the same Claude project, the project knowledge is already shared. Just reference "the testbed handoff document" and the conversation can search for it.

---

*© 2026 Intrepid Logic LLC · SDVOSB · All rights reserved.*
