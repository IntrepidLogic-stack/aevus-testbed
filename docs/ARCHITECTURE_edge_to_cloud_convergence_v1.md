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
