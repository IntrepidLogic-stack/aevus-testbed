# Aevus Monitoring Coverage Plan

**Status:** Draft for review
**Last updated:** 2026-05-20
**Author:** Dave Spencer / Claude
**Scope:** Closing the gap between the current polling-only testbed and a field-grade SCADA event-capture architecture.

---

## 1. Where we are today

The testbed has a complete **polling** leg:

- 5s Modbus TCP poll of the SCADAPack 470 (10 holding registers + 4 discrete inputs)
- 30s SNMP v2c poll of the Trio JR900 radios, MikroTik L009, and Cisco Catalyst 2960
- Threshold-based vital scoring → `AlertEngine.evaluate()`
- Comms-loss detection via staleness sweep + per-cycle offline check (3× missed polls → CRITICAL)
- Partial-telemetry detection via expected-metrics diff (1 poll cycle → WARNING)
- Health score computation, prediction loop, WebSocket fan-out

**What this delivers:** correct values within one poll interval, comms loss within ~15s for the RTU and ~90s for the network/RF gear, and single-channel sensor faults within one cycle.

**What this does NOT deliver:** sub-second event capture. Anything that happens between two polls is invisible until the next scrape — up to 5s for the RTU, up to 30s for everything else. Real field SCADA closes this gap with **asynchronous push** alongside polling: SNMP traps, DNP3 unsolicited responses, and syslog.

We have one leg of a three-leg stool.

---

## 2. Coverage gap matrix

| Failure mode | Field-SCADA mechanism | Today |
|---|---|---|
| Ethernet cable unplugged | SNMP linkDown trap | ❌ poll lag up to 30s |
| RF carrier loss / link flap | Vendor RF trap on JR900 | ❌ inferred from next 30s RSSI poll |
| RTU cold start / reboot | SNMP coldStart trap, DNP3 unsolicited Class 0 | ❌ inferred from uptime regression |
| RTU process alarm latched (high pressure, low battery, comm fault) | DNP3 unsolicited Class 1/2/3 | ⚠️ polled via discrete inputs, 5s lag; DNP3 collector not built |
| Auth failure / unauthorized config change | SNMP authenticationFailure trap, syslog | ❌ no syslog or trap receiver |
| Power-supply / UPS failure | UPS-MIB (RFC 1628) trap | ❌ no UPS integration |
| Cabinet door / tamper switch | Discrete input → DNP3 event | ❌ not wired |
| Network-down vs agent-down | ICMP probe in parallel | ❌ cannot distinguish today |
| NTP drift / time skew | SNMP / NTP probe | ❌ not collected |
| Out-of-band reachability when in-band is down | Uplogix 5000 console | ⚠️ box is in the rack, not integrated |
| Configuration drift | Periodic config hash diff | ❌ not collected |

---

## 3. Phased buildout

Each phase lists deliverable code modules, effort, dependencies, and acceptance criteria. Phases can be executed in parallel where dependencies allow; the sequence below is the recommended single-thread order based on **board-audit value × build cost × patent leverage**.

### Phase 1 — SNMP Trap Receiver  *(~1 day)*

**Why first:** highest coverage gain per hour of work. Every SNMP device on the lab (radios, router, switch, and most field gear we'll encounter) emits standard traps for cable unplug, cold start, and auth failure. A trap receiver gives us **sub-second** detection on every one of those events without changing the polling cadence.

**Deliverables**
- `src/collectors/snmp_trap_receiver.py` — async UDP 162 listener using `pysnmp.entity.engine`, decodes SNMPv2c traps, parses standard MIB-II + vendor varbinds.
- New event source pattern: trap-driven collectors **push** into a shared event bus instead of being polled. Bus consumed by `AlertEngine.evaluate_event()` (new).
- `src/engine/alert_engine.py::evaluate_event(event_type, asset_id, varbinds)` — maps OID-keyed traps to alerts. Initial coverage:
  - `linkDown` / `linkUp` → critical / auto-resolve
  - `coldStart` / `warmStart` → warning
  - `authenticationFailure` → critical (security)
- Configuration on each managed device to point trap target at the edge collector (manual one-time step, documented).
- Trap inventory doc per vendor (Trio, MikroTik, Cisco) listing OIDs we care about.

**Dependencies**
- Trap target must be configured on each device. MikroTik and Cisco done via existing console access; Trio JR900 needs serial config (already a pending item).

**Acceptance**
- Pull a cable between MikroTik ether3 and SHOP-01 → `linkDown` alert in dashboard within 2 seconds (target: <500ms).
- Reboot a JR900 → `coldStart` alert before the next 30s poll cycle.
- Unit tests verify OID→alert mapping; integration test using a `pysnmp` test trap generator.

---

### Phase 2 — ICMP Layer-3 Probe  *(~half day)*

**Why second:** trivially cheap, and it gives the dashboard a *true* "network reachable" signal independent of any agent or protocol. Lets us distinguish "device dead" from "SNMP agent dead" from "Modbus port closed" — operational gold.

**Deliverables**
- `src/collectors/icmp_probe.py` — 1s interval ping to every registered asset's `host`. Tracks loss rate and RTT.
- New asset vital: `REACHABILITY` with values `up`, `degraded` (>10% loss), `down` (3 consecutive timeouts).
- Sub-second OFFLINE detection that fronts the existing comms-loss path: if ICMP is down for >3s, we don't wait for the SNMP/Modbus staleness sweep.
- Latency / jitter time-series in InfluxDB.

**Dependencies**
- Edge collector must run with `CAP_NET_RAW` (or use unprivileged ICMP on Linux via `net.ipv4.ping_group_range`). Documented in deploy notes.

**Acceptance**
- Power-off a device → `REACHABILITY=down` within 3s, before any other alert.
- Block ICMP via firewall (simulate path issue) → `REACHABILITY=down` but SNMP poll still succeeds → dashboard shows the distinction cleanly.

---

### Phase 3 — DNP3 Unsolicited Responses  *(~2 days)*

**Why third:** highest patent leverage. The SCADAPack 470 outstation is already configured to send unsolicited Class 1/2/3 events; we just don't have a collector listening. Building this delivers **millisecond-latency process alarms** — the "AI knows before the operator" story for the UXDA submission and the P-008 patent provisional. Polling-only competitors literally cannot match this latency.

**Deliverables**
- `src/collectors/dnp3_outstation.py` — DNP3 master implementation (TCP 20000, master addr 1, outstation addr 10) using `dnp3-python` or `opendnp3`. Listens for unsolicited responses, decodes Binary Input Change events and Analog Input Change events.
- Event-driven path into `AlertEngine.evaluate_event()` — reuses the same bus introduced in Phase 1.
- Integrity poll on connect / reconnect to sync state.
- Class 1/2/3 mapping documented per the SCADAPack point list.
- IL-9000 interlock unchanged (DNP3 is read path; firmware writes are still gated).

**Dependencies**
- SCADAPack 470 must be physically online and configured. Currently pending network visibility (CLAUDE.md status).
- DNP3 library choice — `opendnp3` (C++ bindings, mature) vs. `dnp3-python` (pure Python, lighter). Evaluation needed.

**Acceptance**
- Latch the high-pressure alarm on the SCADAPack → critical alert in dashboard within 500ms.
- Compare against Modbus-polled detection of the same event → DNP3 path measurably faster. Pin the timing diff in a test.
- Outstation reboot → integrity poll repopulates Class 0 state without operator intervention.

---

### Phase 4 — Syslog Receiver  *(~1 day)*

**Why fourth:** catches the long tail — config changes, login events, BGP / OSPF flaps, MikroTik's chatty operational logs, and anything the vendors didn't bother to define an SNMP MIB for. Critical for IEC 62443 audit trail.

**Deliverables**
- `src/collectors/syslog_receiver.py` — UDP 514 listener with RFC 5424 parser. Optional TLS for syslog-ng / rsyslog upstream.
- Rule-based pattern matcher: regex → asset + severity. Initial ruleset for MikroTik (login, config change, interface state), Cisco (link, OSPF, %SEC-LOGIN), Schneider SCADAPack.
- Raw log persistence in SQLite (90-day rotation) for compliance.
- Dashboard tile: recent security events per asset.

**Dependencies**
- Each managed device pointed at the edge collector for syslog. Documented one-time config.

**Acceptance**
- Log into MikroTik via WinBox → `LOGIN_SUCCESS` event surfaces in dashboard within 2s with username and source IP.
- Change a firewall rule → `CONFIG_CHANGE` event with diff if available.

---

### Phase 5 — Uplogix 5000 Out-of-Band Integration  *(~1.5 days)*

**Why fifth:** separates "we can't reach the device" from "we can't reach the *path* to the device." Field SCADA gold — and the Uplogix is already in the rack. Below trap/syslog priority because in-band coverage matters more day-to-day, but this is what makes us defensible in a NOC RFP.

**Deliverables**
- `src/collectors/uplogix_oob.py` — talks to the Uplogix 5000's REST/SSH interface (TBD after console config). Tracks console-server reachability to each managed device.
- New asset vital: `OOB_REACHABILITY` — green when console path is intact even if Ethernet is down.
- Failover narrative on the dashboard: "Device unreachable in-band, but console responds — likely a network path issue, not a device failure."

**Dependencies**
- Uplogix 5000 needs initial console configuration (pending).

**Acceptance**
- Pull the Ethernet cable on a managed device but leave its console connected → dashboard shows "in-band down, console responsive" within 5s.

---

### Phase 6 — UPS / Power Monitoring  *(~half day, when a UPS is in scope)*

**Deliverables**
- `src/collectors/snmp_ups.py` — standard UPS-MIB (RFC 1628) poll + trap subscription.
- Vitals: `INPUT_VOLTAGE`, `OUTPUT_LOAD`, `BATTERY_RUNTIME`, `ON_BATTERY` (binary).
- Critical alert on `ON_BATTERY=true`; warning on `BATTERY_RUNTIME < 10 min`.

**Dependencies**
- Requires a UPS with SNMP card on the lab network. Not currently present.

**Acceptance**
- Trip the lab UPS to battery → critical alert within 1 poll cycle + trap-driven alert immediately (depends on Phase 1).

---

### Phase 7 — Configuration Drift Detection  *(~2 days)*

**Why last:** lower urgency than the event-capture work above, but expected at the ISA-101 / IEC 62443 levels we're pursuing. Catches the unauthorized-change failure mode that traps and syslog might miss if logging was disabled by the same actor.

**Deliverables**
- `src/engine/config_drift.py` — periodic (1h) fetch of running config from network gear via SSH/SNMP, normalized hash, diff against baseline.
- Baseline approval workflow: change detected → warning alert → operator either acknowledges (new baseline) or rejects (incident).
- Per-device baselines stored in SQLite with audit history.

**Dependencies**
- Vendor-specific config fetch (Cisco CLI, MikroTik export, Schneider). Some complexity.

**Acceptance**
- Manually change a Cisco port description → drift detected within 1h, alert raised, diff visible in dashboard.

---

## 4. Sequencing against company milestones

| Milestone | Required phases |
|---|---|
| Next 31-member advisory board audit | Phases 1, 2 minimum (event timeliness + L3/L7 distinction). Phase 3 strongly preferred (DNP3 unsolicited is the differentiator). |
| UXDA submission expansion | Phase 3 visualization — "AI knows in milliseconds" demo. The before/after latency screenshot is the strongest single asset. |
| P-008 patent provisional support | Phase 3 — DNP3 unsolicited + AI inference as the claimed invention. |
| IEC 62443 / NIST 800-82 audit prep | Phases 1, 4, 7 (event capture + audit trail + drift detection are explicit controls). |
| Federal contracting (SDVOSB pursuits) | Full stack through Phase 5 (out-of-band reachability is a hard requirement in most DoD SCADA RFPs). |

**Recommended single-thread order:** 1 → 2 → 3 → 4 → 5 → 6 → 7.
**Total effort to reach board-audit-ready (Phases 1–3):** ~3.5 working days.
**Total effort to full coverage:** ~9 working days.

---

## 5. Open architectural questions

1. **Event bus pattern.** Phase 1 introduces an async event source for the first time. Options:
   - Simple `asyncio.Queue` consumed by a single dispatcher task (lightest, what I'd recommend for now).
   - Redis Streams (overkill until we have multiple edge collectors).
   - NATS (right answer at fleet scale, premature now).

2. **DNP3 library choice.** `opendnp3` is the reference implementation; `dnp3-python` is lighter but less battle-tested. Need a spike before committing.

3. **Edge collector privileges.** ICMP and SNMP trap receiver both need privileged ports / capabilities. We should decide whether the collector runs as a systemd service with `CAP_NET_RAW` + `CAP_NET_BIND_SERVICE`, or as root with `NoNewPrivileges=true`. The former is cleaner.

4. **Trap authentication.** SNMPv2c traps are unauthenticated UDP. For the lab this is fine. For any deployment beyond the testbed we should plan a path to SNMPv3 with `authPriv`.

5. **Where event-driven alerts live in the dashboard.** Today the dashboard polls the REST API. Trap-driven and DNP3-driven alerts will arrive faster than the next REST refresh, so the WebSocket push path becomes the critical real-time channel. Worth a Phase 1 dashboard sweep to make sure WS reconnect handling is robust.

6. **Compliance evidence collection.** Each phase should write its events into a tamper-evident audit log (hash-chained or append-only). Worth designing once in Phase 1 rather than retrofitting later.

---

## 6. Risks if we don't do this

- **Field demo blowup.** If a prospect unplugs a cable during a live demo and the dashboard takes 30s to react, we lose the room. We just hit this exact failure mode internally with the JR900/SCADAPack power test — the bug is fixed but the *visibility window* is still polling-cadence.
- **Patent prior-art exposure.** P-008's defensibility leans on real-time inference. Without DNP3 unsolicited, our latency claim is "5s" — competitors can match that with polling alone.
- **Audit findings.** The board audit and any 62443 audit will mark us on event timeliness and audit trail. Phase 1 + Phase 4 are the explicit asks.
- **Operations cost at scale.** Polling 23 devices is cheap. Polling 23,000 isn't. Event-driven architecture scales horizontally; polling-only does not.

---

## 7. Recommendation — APPROVED 2026-05-20

**Approved execution sequence (Dave, 2026-05-20):**

1. **Stay local for Phases 1–3** of the coverage plan (trap receiver, ICMP probe, DNP3 unsolicited). Plain Python modules built and tested against real lab hardware before any cloud refactor.
2. **Wrap the collector in Greengrass v2** as the bridge step — same code, managed runtime. ~1-day exercise: define each collector as a Greengrass component with a recipe, deploy via Greengrass CLI. No new functionality, just operational maturity.
3. **Land IoT Core MQTT + SiteWise** as the cloud landing zone. Greengrass components publish to MQTT topics; SiteWise ingests via IoT Core rule. Dashboard moves to MQTT-over-WSS subscriptions.
4. **Bedrock for AI root cause** stays the plan per global rules. SiteWise's built-in L4E (Lookout for Equipment) piloted alongside for vibration anomaly.
5. **Defer IoT Events** — our alert engine is more capable for our use case. Revisit only if end customers need visual rule editing.

This sequence supersedes any earlier proposals in §3 / §10. The work order below remains the canonical roadmap.

### Original recommendation (retained for context)

**Lock the trap receiver (Phase 1) and ICMP probe (Phase 2) before the next board audit.** Schedule DNP3 (Phase 3) immediately after — it's the deliverable that pays off three commitments (board audit, UXDA, patent provisional) in one build. Phases 4–7 sequence behind those based on contract timing.

---

## 8. AWS / IoT layer — current state and target

**Today:** zero AWS surface. Everything runs on the Raspberry Pi edge collector — Python + FastAPI + InfluxDB + SQLite + APScheduler. Appropriate for a lab prototype, inappropriate for production midstream or federal SCADA deployments.

**Target pattern:** hybrid — **Greengrass at the edge, IoT Core + SiteWise in the cloud, Bedrock for inference.** Edge keeps sub-second alarming (DNP3 unsolicited, SNMP traps, ICMP) so WAN loss doesn't blind the field; cloud holds the fleet view, the canonical asset model, the AI horsepower, and the audit log.

A dedicated brief lives at `docs/AWS_LANDING_ZONE.md` covering Greengrass component design, IoT Core topic hierarchy, SiteWise asset model, IAM, and networking. This section is the integration map between the coverage phases above and the AWS layer.

## 9. AWS service mapping per coverage phase

| Coverage Phase | Stays local (Greengrass) | Cloud-side (IoT Core / SiteWise / etc.) |
|---|---|---|
| Phase 1 — SNMP traps | Trap receiver component listening on UDP 162 | Events publish to `aevus/{site}/{asset}/events/snmp-trap` MQTT topic; SiteWise alarm model fires fleet-view alert |
| Phase 2 — ICMP probe | Probe component, 1s interval, local reachability state | Reachability state delta published to `aevus/{site}/{asset}/state/reachability`; surfaces on fleet dashboard |
| Phase 3 — DNP3 unsolicited | DNP3 master component (latency-critical, MUST stay edge) | Class 1/2/3 events publish to `aevus/{site}/{asset}/events/dnp3`; Bedrock root-cause inference invoked via Lambda on critical events |
| Phase 4 — Syslog | Syslog receiver component on UDP 514 | Parsed events to `aevus/{site}/{asset}/events/syslog`; raw logs to S3 with Object Lock (compliance) |
| Phase 5 — Uplogix OOB | Uplogix bridge component | `aevus/{site}/{asset}/state/oob-reachability` topic; distinguishes "in-band down, OOB up" at fleet level |
| Phase 6 — UPS / power | UPS-MIB SNMP component | Standard SiteWise asset model for UPS class |
| Phase 7 — Config drift | Diff engine runs on Greengrass (avoids egress of full configs) | Drift events to `aevus/{site}/{asset}/events/drift`; baselines stored encrypted in S3 |

**Cross-cutting:**
- Every event lands in CloudTrail (control-plane) + S3 Object Lock (event-plane) for IEC 62443 / NIST 800-82 audit evidence — solves the §5 audit-log open question.
- All time-series flows to SiteWise (asset properties) and Timestream-for-InfluxDB (raw retention) via IoT Core rules — preserves the InfluxQL we already write against.
- Bedrock is invoked from Lambda on critical events for root-cause narrative generation (per global rules: AWS Bedrock is the standard for AI).

## 10. AWS sequencing alongside the coverage phases

Recommended ordering (does not delay Phases 1–3, which build locally first):

| Step | Work | Effort | When |
|---|---|---|---|
| AWS-0 | Confirm AWS Activate credit tier; check SDVOSB eligibility for additional credits. See `docs/AWS_ACTIVATE_CREDITS_CHECK.md`. | ~half day (mostly waiting on portal) | **Before any spend** |
| AWS-1 | Stand up minimal IoT Core + Greengrass v2 in the existing IL AWS account (676433090238). Register the Pi as a Greengrass core device. | ~1 day | After coverage Phase 2 lands locally |
| AWS-2 | Refactor existing collectors into Greengrass v2 components. Same code, recipe + deployment surface. | ~1.5 days | After AWS-1 |
| AWS-3 | Define SiteWise asset model (asset types: radio, rtu, switch, router, ups). Wire IoT Core rule → SiteWise property updates. | ~1 day | Parallel with AWS-2 |
| AWS-4 | Move dashboard from FastAPI WebSocket to MQTT-over-WSS (or AppSync subscriptions). Keep FastAPI for REST control plane. | ~2 days | After AWS-3 |
| AWS-5 | Bedrock-backed root-cause Lambda on critical events. Feed: asset properties + recent events + relevant time-series window. | ~1.5 days | After Phase 3 (DNP3) lands |
| AWS-6 | CloudTrail + S3 Object Lock audit log, IAM Identity Center for operator access, OIDC for GitHub Actions deploys. | ~1 day | Before any federal pursuit |

**Total AWS layer effort:** ~8 working days, parallelizable with coverage phases.
**Earliest production-ready (coverage Phases 1–3 + AWS-1 through AWS-3):** ~7 working days from today.

## 11. What AWS does NOT replace

- **The bugs we just fixed** (comms-loss, partial telemetry) — application logic, identical regardless of runtime.
- **The seven coverage phases above** — every one of them still needs to be built. Greengrass is a deploy/run surface, not a feature.
- **IL-9000 safety interlock** — stays in code, not a cloud control.
- **DNP3 unsolicited collector** — the patent-relevant piece lives at the edge. AWS receives its events but cannot replace it (latency).
- **AI/ML strategy clarity** — Bedrock per global rules; SiteWise's built-in Lookout for Equipment (L4E) is worth piloting alongside for vibration/RF anomaly, but the choice is ours.
