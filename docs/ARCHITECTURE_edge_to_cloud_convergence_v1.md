# Aevus Telemetry Architecture — Edge→Cloud Convergence (v1)

**Status:** Proposed (target-state). Lab today runs the interim dual-path
described in §2. This doc is the north star for "how does Aevus scale and stay
OT-secure" — the answer to that question on an enterprise sales/architecture
slide.

**Author:** Engineering (Woody)
**Date:** 2026-05-29
**Related tasks:** #93/#94 (bridge), #131/#138 (Trio collectors), #145 (uptime),
#146/#147 (Invoice Ninja + SNS noise — unrelated), this doc's follow-ups below.

---

## 1. Why this doc exists

While wiring real Trio JR900 firmware to the dashboard we hit a symptom of a
deeper architecture smell: **two systems both claim to own the same asset's
truth.** The Raspberry Pi edge collector polls the real radios over SNMP; the
EC2 cloud instance *also* tries to (and silently fell back to a **simulator**
when its config lacked the radio IPs). The dashboard showed fabricated RSSI and
a blank firmware field as a result.

For a 2-radio lab this is harmless and we patched it tactically (set the radio
IPs in EC2's `.env` so EC2 polls the real devices — see §2). But the same
pattern in an enterprise oil & gas deployment (hundreds of sites, thousands of
nodes, millions of points) is disqualifying. This doc defines the solid,
scalable target and a migration path.

---

## 2. Current (interim) architecture — and its problems

```
                 ┌──────────────────────── OT LAN (192.168.88.0/24) ───────┐
                 │  Trio radios · SCADAPack RTU · MikroTik · Catalyst       │
                 └───▲───────────────────────────────────▲──────────────────┘
                     │ SNMP/Modbus/DNP3 (correct)         │ SNMP over Tailscale
                     │                                    │  (PROBLEM: cloud
            ┌────────┴────────┐                  ┌────────┴─────────┐  reaching
            │  Pi edge        │                  │  EC2 cloud       │  into OT)
            │  aevus.service  │                  │  aevus.service   │
            │  (real poller)  │                  │  (ALSO polls;    │
            └───┬─────────────┘                  │   sims on miss)  │
                │ MQTT→IoT Core (built, #61)      └───┬──────────────┘
                │ + Pi-poll bridge (#94) ───────────► │ writes EC2 SQLite
                ▼                                      ▼
            AWS IoT Core / S3 (#62)            Dashboard reads EC2 SQLite
```

**Anti-patterns in the interim design:**

1. **Dual ownership / split-brain.** Both the Pi and EC2 poll the same assets.
   Whichever writes the EC2 SQLite last wins → flapping risk; inconsistent
   truth.
2. **Cloud reaches into the OT LAN.** EC2 polls `192.168.88.x` over a Tailscale
   subnet route. This violates OT/IT segmentation (Purdue / ISA-95, IEC 62443).
   A cloud VPC able to reach a compressor-station RTU is an automatic audit
   finding — and for Aevus, *avoiding* this is a sales differentiator.
3. **Silent simulator substitution.** When a real poll fails, the code falls
   back to `SimulatorCollector` and writes fabricated values into the *same*
   asset fields. "Offline" became "-62 dBm." Operators can't trust a value that
   might be invented.
4. **Bespoke SQLite-copying bridge** (`aevus_bridge_v2.py`) shuttles a subset of
   assets Pi→EC2. It's a maintenance liability and forwards an ad-hoc field
   whitelist (it silently dropped `firmware` until 2026-05-29).

**Tactical fixes already applied (keep the lab working, NOT the target):**
- EC2 `.env`: `RAD_01_IP=192.168.88.11`, `RAD_02_IP=192.168.88.12` so EC2 polls
  the real radios instead of simulating. ⚠️ **Out-of-band config — not in IaC.**
- Bridge `update_pi_real_asset()` now forwards `firmware` (COALESCE-guarded).

---

## 3. Target architecture — edge pushes, cloud subscribes

```
   OT devices ──poll──►  EDGE GATEWAY (Pi / Greengrass)   ◄── ONLY OT talker
                              │  normalize · health · store-and-forward
                              ▼  MQTT (Sparkplug B) northbound, TLS
                         AWS IoT Core  (ingest · fan-in · authz per-thing)
                              │  IoT Rules
              ┌───────────────┼────────────────────────┐
              ▼               ▼                         ▼
       SiteWise / TSDB   DynamoDB or Device Shadow   S3 (raw archive, #62)
       (history)         (latest-state per asset)
                              │
                              ▼
                   Cloud read-API + dashboard   ◄── reads stores; NEVER polls OT
```

### Principles (the non-negotiables)

1. **Edge owns acquisition; cloud owns aggregation + presentation.** Only edge
   gateways speak SNMP/Modbus/DNP3. The cloud is receive-only. One direction.
2. **One owner per asset.** Each device is polled by exactly one edge gateway
   (the nearest). No second poller.
3. **Offline is explicit, never simulated.** A missed poll marks the asset
   `stale`/`offline` (we already built the real-time stale banner + 24h uptime
   %, #145). Simulated/demo data lives in a **separate, clearly-flagged
   namespace** (`source=simulator`) and is never written into a real asset's
   live fields.
4. **Cloud read-API is a thin reader** over the cloud stores — it does not poll,
   does not simulate, does not run device collectors.

### Why it scales to "tons of nodes"

- **Fan-in, not fan-out.** Thousands of edge gateways publish northbound; IoT
  Core handles millions of concurrent things. Add capacity by adding
  *publishers*, never by teaching a central poller about more IPs.
- **Decoupled tiers.** Ingestion (IoT Core) ‖ storage (TSDB) ‖ presentation
  (API) scale independently. A dashboard traffic spike never slows device
  polling.
- **Store-and-forward at the edge** (Greengrass stream manager, #16–19)
  survives WAN/cell/satellite outages at remote pads — telemetry buffers and
  replays on reconnect.
- **Latest-state store** (DynamoDB or IoT Device Shadow, one item per asset)
  gives the dashboard O(1) current-value reads instead of scanning N devices.
- **Sparkplug B** payload spec gives birth/death certificates, auto-discovery,
  and explicit online/offline state — so "no data" is unambiguous, never a
  guess. Adopt as the fleet grows past the lab.

---

## 4. What Aevus already has vs. needs

| Capability | Status |
|---|---|
| Edge collector (Pi) polling OT | ✅ built |
| MQTT publisher → AWS IoT Core | ✅ built (#20–25, #61) |
| IoT Core → S3 raw archive | ✅ built (#62) |
| SiteWise asset model | ✅ TF exists (#24) |
| Greengrass nucleus + components | ✅ built (#16–19) |
| **Latest-state store (DynamoDB/Shadow) for dashboard reads** | ❌ to build |
| **Cloud read-API reads stores (not EC2 SQLite, not polling)** | ❌ to build |
| **Retire EC2-side OT polling + simulator fallback** | ❌ to do |
| **Retire `aevus_bridge_v2.py` SQLite copier** | ❌ to do |
| Sparkplug B payloads | ❌ future (post-lab) |

**~80% of the target is already built.** The work is *convergence*: route the
dashboard onto the existing MQTT/IoT-Core path and remove the parallel
pull/bridge/simulate path.

---

## 5. Migration path (phased, low-risk)

**Phase 0 — today (done):** Lab works via EC2 polling radios directly + bridge
for RTR/SW/EDGE. Tactical, documented as interim.

**Phase 1 — latest-state store.** IoT Rule → DynamoDB (or enable Device Shadow)
writing one item per asset from the edge's existing MQTT stream. No dashboard
change yet.

**Phase 2 — cloud read-API points at the store.** Switch the EC2 FastAPI
`/api/v1/assets` to read DynamoDB latest-state + SiteWise history instead of
local SQLite. Dashboard untouched (same JSON contract).

**Phase 3 — stop the cloud polling OT.** Remove `_register_real_snmp_collectors`
radio/network targets on EC2; remove the EC2 `.env` OT IPs; drop the Tailscale
subnet route from EC2. EC2 no longer touches the OT LAN. ✅ segmentation.

**Phase 4 — retire the bridge.** Delete `aevus_bridge_v2.py` + its systemd unit
once all assets flow via MQTT→store. Probe pseudo-assets (PI-01/SHOP-01/WAN-01)
move to edge-published health.

**Phase 5 — Sparkplug B + multi-gateway.** Adopt Sparkplug for explicit state;
onboard additional edge gateways per site; regional broker tier if needed.

---

## 6. Decision log

- **2026-05-29:** Chose tactical Option B (EC2 polls real radios) to unblock the
  firmware display for the lab demo, with this convergence doc as the committed
  real fix. Rationale: 2-radio lab; reversible; the enterprise answer is the
  edge-push model above, tracked as Phase 1–4 follow-ups.

---

## 7. Industry reference & standards (the enterprise IIoT/SCADA answer)

This section records the canonical industry design Aevus converges toward, with
the real standards, patterns, and product landscape — for the enterprise /
investor / security-review conversation.

### 7.1 The pattern: Unified Namespace (UNS) on MQTT + Sparkplug B

The convergent modern IIoT design is a **Unified Namespace** — a single,
structured, real-time, business-contextualized source of truth that every
system publishes to and subscribes from:

- **One broker = single source of truth.** Topic hierarchy mirrors the business:
  `enterprise/site/area/line/cell/asset/metric`. PLCs, SCADA, MES, ERP,
  analytics, dashboards all publish current state and subscribe to what they
  need. **No point-to-point integrations** — producers and consumers are fully
  decoupled. (Pattern popularized by the "Industry 4.0" community; now the
  default reference design.)
- **Report-by-exception**, not poll-everything: a device publishes only on
  change. At thousands of nodes × thousands of points this is the difference
  between a feasible system and a saturated network/historian.
- **Last-known-value retained** at the broker (MQTT retained messages): any new
  consumer instantly has current state without polling anyone.

**Sparkplug B** (Eclipse Foundation open spec) sits on top of MQTT and is the
piece that structurally eliminates the bugs we hit in the lab:

- **Stateful session awareness:** `NBIRTH`/`DBIRTH` (online + full tag
  definitions), `NDATA`/`DDATA` (changes), `NDEATH`/`DDEATH` via MQTT
  Last-Will → instant, unambiguous OFFLINE. A consumer always knows whether data
  is live, stale, or dead → **a real asset's fields can never silently show a
  fabricated value** (the exact failure mode of our simulator fallback).
- **Self-describing payloads** + auto-discovery of new assets.

### 7.2 Protocol layering: OPC-UA at the edge, MQTT/Sparkplug for transport

The two giants are **OPC-UA** (OT interoperability standard — pub/sub +
per-industry companion specs) and **MQTT/Sparkplug**. The mature answer layers
them:

- **OPC-UA / Modbus / DNP3 / SNMP** at the device-and-edge layer (acquisition).
- **MQTT + Sparkplug B** for transport edge → UNS → cloud.

MQTT won the transport layer largely because it is **outbound-only from OT** —
the edge dials *out* to the broker, so no inbound hole is opened into the plant
network. This is the IEC 62443 / Purdue-friendly property that lets security
teams approve it. (Cloud reaching *into* the OT LAN — what the interim EC2 path
does — is precisely what this architecture forbids.)

### 7.3 Segmentation & security: Purdue / ISA-95 + IEC 62443

- **Levels:** L0 sensors/actuators → L1 PLC/RTU → L2 SCADA/HMI → L3
  MES/historian → **L3.5 OT/IT DMZ** → L4/L5 enterprise/cloud. Nothing skips the
  DMZ; cloud never originates connections into OT.
- **IEC 62443** for the security program: zones & conduits, signed firmware,
  zero-trust, least privilege.
- **No remote writes to safety-critical devices** — Aevus's **IL-9000 interlock**
  (P-008) is exactly this enterprise posture encoded in software: the platform
  stages/verifies/schedules firmware but a credentialed tech performs the final
  write on site.

### 7.4 Contextualization, historian & digital twin

- **Edge contextualization ("DataOps"):** raw tags → modeled assets *before*
  they leave the edge (HighByte Intelligence Hub, Ignition UDTs, ISA-95
  equipment models). The UNS carries modeled assets, not raw register dumps.
- **Historian / TSDB:** AVEVA PI (OT incumbent), InfluxDB, TimescaleDB, AWS
  Timestream, Azure Data Explorer.
- **Digital twin / asset model:** AWS IoT TwinMaker / SiteWise, Azure Digital
  Twins. Gives the AI/RCA layer a structured world model to reason over.

### 7.5 Product landscape (what enterprises buy/build with)

| Layer | Representative options |
|---|---|
| SCADA / edge platform | **Ignition** (MQTT-native, modern default), AVEVA, GE Proficy, Siemens WinCC, Rockwell FactoryTalk |
| Edge contextualization | **HighByte Intelligence Hub**, Litmus Edge, Ignition UDTs |
| MQTT broker (UNS) | **HiveMQ**, **EMQX** (enterprise Sparkplug), AWS IoT Core, Azure IoT Hub |
| Edge runtime / fleet mgmt | **AWS IoT Greengrass**, Azure IoT Edge, balena |
| Historian / TSDB | AVEVA PI, InfluxDB, TimescaleDB, AWS Timestream |
| Digital twin / asset model | AWS TwinMaker / SiteWise, Azure Digital Twins, ISA-95 |
| IT-side streaming/analytics | Kafka / Kinesis → lakehouse (Databricks/Snowflake) → ML |

### 7.6 Software-engineering discipline

Streaming-first, event-driven; schema registry/contracts (Sparkplug
self-describes, or Avro/Protobuf in Kafka); idempotent consumers; dead-letter
queues; backpressure; **data-freshness as an SLO** (our real-time stale banner +
24h uptime % are the seed of this); GitOps + IaC for the whole pipeline; edge
fleet OTA via managed deployments; pipeline observability.

### 7.7 Aevus positioning (one-line)

> **A Unified Namespace on MQTT + Sparkplug B, fed by edge gateways doing
> OPC-UA/Modbus/DNP3/SNMP acquisition and contextualization, with OT/IT
> segmentation per IEC 62443, a historian + digital-twin model, and the Aevus
> cloud/AI (Bedrock RCA) as a *subscriber* — never a poller.**

This is the slide answer to "how does Aevus scale to thousands of nodes and stay
OT-secure." Aevus already has the edge collector, MQTT→IoT Core publisher
(#20–25, #61), IoT→S3 archive (#62), a SiteWise asset model (#24), and Greengrass
(#16–19). Phases 1–4 (§5) converge onto this path; **Phase 5 adopts Sparkplug B
+ a true UNS broker (HiveMQ/EMQX)** as the fleet grows past the lab.
