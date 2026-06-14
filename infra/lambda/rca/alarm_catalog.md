# Aevus Operational Alarm Catalog — v1

**Document owner:** Intrepid Logic LLC — Aevus product team
**Standard alignment:** ISA-18.2 (Management of Alarm Systems for the Process Industries), API 1167, NIST SP 800-82 Rev. 3
**Audience:** Pilot prospects, integration partners, internal engineering
**Status:** v1 — operative as of 2026-05-27

---

## 1. Purpose

This catalog defines the operational alarm set that ships with Aevus out of the box. It is the SCADA-engineer-grade list — not a marketing list. Every alarm in this catalog has:

- A specific triggering condition with units and durations
- An ISA-18.2 priority band
- A clear operator response expectation
- A defined deadband or persistence requirement (no chatter by design)

Aevus is **monitoring-and-narrative only** under the IL-9000 safety interlock. No alarm in this catalog initiates a write-back to the controlled equipment. Recommended actions terminate at "dispatch credentialed technician." This is enforced in code (`src/il9000.py`), not policy.

---

## 2. ISA-18.2 priority model

| Priority | Band | Operator response window | Examples |
|---|---|---|---|
| **P1** | Critical | ≤ 1 minute | Vessel overpressure HIHI, RTU offline, ESD active |
| **P2** | High | ≤ 10 minutes | Pressure HI, battery LO, vibration HI, link down |
| **P3** | Medium | ≤ 1 hour | Pressure WARN, RSSI margin shrinking, CPU high, maintenance due |
| **P4** | Low / Info | Best effort, dashboard-tile only | Asset rediscovered, firmware version detected |
| **Diagnostic** | Predictive | Surface in Predictions tab, not the alarm horn | Bearing trending, battery aging, L4E anomaly score |
| **Cyber** | Compliance | Routed to separate security channel | SNMP auth failure, unauthorized config write attempt |

Aevus dashboards group alarms by band, never mix bands in the same operator tile, and rate-limit horns and SMS to P1+P2 only by default. This is ISA-18.2 §6 conformance.

---

## 3. P1 — Critical (operator response ≤ 1 min)

| ID | Alarm | Asset class | Trigger | Persistence | IL-9000 |
|---|---|---|---|---|---|
| A-P1-01 | HIHI suction pressure | RTU / PLC | > 900 PSI | 5 s | Narrative only |
| A-P1-02 | HIHI discharge pressure | RTU / PLC | > 1400 PSI | 5 s | Narrative only |
| A-P1-03 | LOLO battery voltage | RTU | < 11.5 VDC | 30 s | Narrative only |
| A-P1-04 | Compressor shutdown active | RTU | Discrete input 10002 = 1 | none | Read-only |
| A-P1-05 | Communication fault (RTU downstream) | RTU | Discrete input 10004 = 1 | none | Read-only |
| A-P1-06 | Asset offline > 5 min | Any | No telemetry in last 5 min | 5 min | n/a |
| A-P1-07 | Vibration HIHI | Rotating eq | > 7.1 mm/s (ISO 10816 Zone D) | 30 s | Narrative only |
| A-P1-08 | ESD / kill-line active | Future / PLC | Configured ESD bit | none | Read-only |

**Why these are P1:** every entry on this list represents either an active safety event, an asset-at-risk condition, or a complete loss of visibility. Operator must acknowledge and dispatch.

---

## 4. P2 — High (operator response ≤ 10 min)

| ID | Alarm | Asset class | Trigger | Persistence |
|---|---|---|---|---|
| A-P2-01 | HI suction pressure | RTU | > 800 PSI | 60 s |
| A-P2-02 | HI discharge pressure | RTU | > 1200 PSI | 60 s |
| A-P2-03 | LO battery voltage | RTU | < 12.0 VDC | 5 min |
| A-P2-04 | Solar voltage fault (daylight) | RTU | < 18 VDC during 0800-1700 local | 10 min |
| A-P2-05 | Vibration HI | Rotating eq | > 4.5 mm/s (ISO 10816 Zone C) | 5 min |
| A-P2-06 | Gas temperature HI | RTU | > 140 °F | 60 s |
| A-P2-07 | Tank level HI | RTU | > 90 % | 60 s |
| A-P2-08 | Tank level LO | RTU | < 10 % | 60 s |
| A-P2-09 | Radio link degraded | Trio JR900 | RSSI < -90 dBm | 5 min |
| A-P2-10 | Radio temperature HI | Trio JR900 | > 75 °C | 5 min |
| A-P2-11 | Network link down | Catalyst / MikroTik | ifOperStatus = down | 60 s |
| A-P2-12 | High packet error rate | Radio or network | > 5 % errors | 5 min |

---

## 5. P3 — Medium (operator response ≤ 1 hour)

| ID | Alarm | Asset class | Trigger | Persistence |
|---|---|---|---|---|
| A-P3-01 | WARN suction pressure | RTU | > 700 PSI | 5 min |
| A-P3-02 | WARN discharge pressure | RTU | > 1100 PSI | 5 min |
| A-P3-03 | Vibration WARN | Rotating eq | > 2.8 mm/s (ISO 10816 Zone B) | 10 min |
| A-P3-04 | Radio RSSI warning | Trio JR900 | < -80 dBm | 10 min |
| A-P3-05 | Radio SNR low | Trio JR900 | < 15 dB | 10 min |
| A-P3-06 | Radio temperature WARN | Trio JR900 | > 60 °C | 10 min |
| A-P3-07 | Network CPU high | MikroTik / Catalyst | > 70 % | 10 min |
| A-P3-08 | Network memory high | Catalyst | Pool used > 80 % | 10 min |
| A-P3-09 | Interface error rate elevated | Network | > 100 errors/min | 10 min |
| A-P3-10 | Flow rate deviation | RTU | ± 25 % from 24 h rolling average | 5 min |
| A-P3-11 | Maintenance interval due | RTU | RunHours crosses next 500-hr boundary | once per crossing |
| A-P3-12 | Alarm chattering detected | Any | Same alarm fires > 5x in 10 min | meta-alarm |

---

## 6. P4 — Low / Informational

| ID | Alarm | Trigger |
|---|---|---|
| A-P4-01 | Asset rediscovered | Returned online after offline event |
| A-P4-02 | Firmware version changed | sysDescr or vendor OID differs from last poll |
| A-P4-03 | Switch port count change | Active port count differs from baseline |
| A-P4-04 | New MAC on access port | First-seen MAC in switch CAM table |
| A-P4-05 | CDP neighbor added/removed | Topology change |
| A-P4-06 | Ambient temperature elevated | Cabinet > 110 °F (not yet bad) |
| A-P4-07 | Edge → cloud latency elevated | p95 > 8 s over 10 min |
| A-P4-08 | RCA narrative ready | Bedrock-generated narrative for any P1/P2 |

---

## 7. Diagnostic / Predictive — surfaced in Predictions tab

These are the patent-relevant differentiators (see P-008 reduction-to-practice record). They produce a **narrative**, not a horn, and never appear in the active alarm count.

| Signal | Asset | Computation |
|---|---|---|
| Bearing condition trending | Rotating eq | Vibration FFT bands trending up over 7-day window |
| Battery health degradation | RTU | Charge/discharge cycle delta narrowing |
| Solar panel soiling | RTU | Peak daily solar V dropping vs irradiance baseline |
| Radio link budget erosion | Radio | RSSI baseline shifting over weeks |
| Compressor cycling anomaly | RTU | Start/stop frequency outside historical band |
| Process drift | RTU | Suction / discharge ratio drifting (efficiency loss) |
| L4E multivariate anomaly | Any | AWS Lookout for Equipment confidence > 0.7 |
| Temperature climb rate | Any | Δ°C/hr exceeding normal warm-up curve |

---

## 8. Cyber / compliance — separate channel

Routed to the IL security SNS topic, not the operator alarm bus. Surfaces in a "Security" panel with audit-log persistence.

| ID | Alarm | Trigger |
|---|---|---|
| C-01 | SNMP auth failure | snmpd auth-trap from any monitored device |
| C-02 | MikroTik failed login attempt | syslog match on auth failure |
| C-03 | RTU config write attempted | DNP3 unauthorized operate → IL-9000 interlock event |
| C-04 | Firmware out-of-band change | Version changed without operator-initiated workflow |
| C-05 | New IP on management VLAN | MAC table sees unknown OUI |
| C-06 | Edge cert expiring | X.509 cert in IoT Core < 30 days to expiry |
| C-07 | Tailscale node added to mesh | Tailscale API audit hook |

---

## 9. Alarm hygiene mechanisms (ISA-18.2 §7, §11)

These are not alarms — they are the platform behaviors that prevent the alarm system from becoming noise.

| Mechanism | Behavior | Reference |
|---|---|---|
| **Deadband / hysteresis** | Each threshold has a 5 % deadband — alarm clears at 95 % of trigger, not 100 % | ISA-18.2 §7.2 |
| **Persistence timer** | Every alarm has a defined "must persist for X seconds" before firing (see tables) | ISA-18.2 §7.3 |
| **Chattering detection** | Same alarm firing > 5x / 10 min → automatic P3 meta-alarm + 30-min shelf | ISA-18.2 §7.5 |
| **Operator shelving** | Manual suppression for maintenance, max 8 hr, audit-logged | ISA-18.2 §11.4 |
| **Alarm flood detection** | > 10 P1/P2 alarms in 60 s → "ALARM FLOOD" banner, operator can switch to flood-view | ISA-18.2 §15 |
| **Maintenance windows** | Bulk-shelve by asset group during scheduled work | ISA-18.2 §11.6 |
| **Stale-data masking** | Alarms suppressed for assets in OFFLINE state — only A-P1-06 fires for those | n/a (Aevus design) |

---

## 10. Alarm lifecycle states

```
OPEN → ACKNOWLEDGED → RESOLVED
  │         │              │
  │         └→ SHELVED ────┘   (operator suspends; auto-unshelves)
  │
  └→ AUTO-RESOLVED (condition cleared without operator action)
```

| State | Visible in operator queue? | Counts in KPI? |
|---|---|---|
| OPEN | Yes — top of queue, sorted by priority then age | Yes |
| ACKNOWLEDGED | Yes — secondary list, operator owns response | Yes |
| SHELVED | Hidden by default, visible in "Shelved" tab | No (but audit-logged) |
| RESOLVED | Hidden by default, visible in History | Historical only |
| AUTO-RESOLVED | Hidden by default, visible in History | Historical only |

---

## 11. Mapping to AWS platform alarms (separate concern)

This catalog covers **equipment-domain** alarms surfaced to the operator. Platform-domain alarms (Pi offline at the OS level, SES bounce rate, Bedrock token spend, etc.) live in CloudWatch and route to the engineering team via `aevus-critical-alerts` / `il-alerts` SNS topics — they do not appear in the operator console. See `il_github_bolt_audit.md` and the platform alarm inventory under CloudWatch dashboard `Aevus-Platform-Ops`.

The one exception: **A-P1-06 (asset offline > 5 min)** is fed by the CloudWatch `aevus-archive-silent` alarm (S3 PutRequests). When that platform alarm fires, the operator console raises A-P1-06 for the affected edge.

---

## 12. Implementation status (as of v1 publication)

| Category | Implemented | Blocked | Planned |
|---|---|---|---|
| P1 alarms | A-P1-06 (asset offline) | Pressure / vibration / compressor: pending SCADAPack 470 IP assignment | — |
| P2 alarms | Radio link, network link, network CPU (via SNMP) | Tank, gas temp, solar — pending RTU online | — |
| P3 alarms | Network CPU, CPU mem, RSSI warning | Run-hours, flow deviation — pending RTU online | Chattering detection (in progress) |
| P4 alarms | RCA narrative ready | — | Firmware version diff (in progress), MAC churn |
| Diagnostic | Bedrock RCA narrative on every P1/P2 | L4E pilot pending bootstrap | Bearing trending, battery aging |
| Cyber | Edge cert monitoring via IoT Audit | — | SNMP auth-trap routing (handler exists, not yet routed) |
| Hygiene | Persistence timers, auto-resolve on clear, ack/resolve API | — | Deadband, shelving, flood detection |

---

## 13. Threshold sources

Every numeric threshold in this catalog traces to one of:

- **ISA-18.2 / ISA-101** — alarm management + HMI guidance
- **ISO 10816** — vibration severity zones for rotating equipment
- **API 1167** — pipeline SCADA alarm management RP
- **NIST SP 800-82 Rev. 3** — ICS security guidance
- **Vendor data sheets** — Trio JR900 thermal/RF limits, SCADAPack 470 register ranges, Cisco IOS / RouterOS operating envelopes

Thresholds are operator-configurable per asset class via the `aevus-testbed` config (defaults in `CLAUDE.md` and asset registry). No threshold is hardcoded in a way that prevents site-specific tuning.

---

## 14. Change log

| Version | Date | Change |
|---|---|---|
| v1 | 2026-05-27 | Initial publication. Aligned with current testbed-kit code + P-008 reduction-to-practice scope. |

---

## Signature

**Document author:** Jon David "Woody" Spencer, CIO, Intrepid Logic LLC
**Standards review:** open — pending review by licensed PE prior to first paying-customer deployment
**Companion documents:** `CLAUDE.md` (architecture + thresholds), `P-008_RTP_evidence.md` (patent reduction-to-practice), `IL_Remote_Access_Standard_v1.md`
