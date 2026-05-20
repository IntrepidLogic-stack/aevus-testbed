# P-008 — Patent Provisional Draft (pre-attorney review)

**Title (working):** Real-Time Industrial Control System Root-Cause Narrative Generation Combining Asynchronous Device-Initiated Event Reporting with Large-Language-Model Reasoning

**Inventor(s):** Dave Spencer (Intrepid Logic LLC)
**Assignee:** Intrepid Logic LLC, Katy, Texas
**Status:** Pre-attorney review. Capture artifact — turn over to patent counsel for §112-compliant rewrite + claim narrowing.
**Created:** 2026-05-20
**Reference number:** P-008 (internal IL invention disclosure tracking)

---

## 0. Purpose of this document

This is the **fresh-context capture** — written immediately after the implementation work that produced the evidence. The intent is to commit the architectural and methodological detail to a fixed document before context decays, so the patent attorney can draft a clean provisional from a complete picture. **Not for filing as-is.**

What this contains:
- Problem statement, prior art summary, and what's novel
- Detailed description of the invention with architecture diagram
- Independent + dependent draft claims (broad to narrow)
- Abstract
- Inventory of evidence already on hand (commits, tests, telemetry shape)

---

## 1. Field of the invention

This invention relates to industrial control system (ICS) monitoring platforms, and more particularly to real-time root-cause analysis combining (a) asynchronous device-initiated event reporting from supervisory-control and data-acquisition (SCADA) field devices and (b) large-language-model reasoning over the captured events plus correlated context.

## 2. Background

### 2a. State of conventional SCADA monitoring

Conventional SCADA monitoring platforms detect events through periodic polling of field devices. A central master station scans each device on a fixed cadence — typically 5 seconds for Modbus over TCP, 30 seconds for SNMP, longer for low-bandwidth radio links — and compares the returned values to operator-configured thresholds. Polling-only architectures have two structural limitations:

1. **Detection latency floor.** Any event that resolves between polls is invisible until the next scrape. Worst-case detection latency equals the poll interval. For safety-significant alarms (overpressure, low battery, communication fault) on a 5s poll, this is a 5s blind window.
2. **No semantic interpretation.** Polling produces a value and a threshold comparison. Operators receive "high pressure alarm at 14:32:05Z" — a fact, not an explanation. Investigation of root cause is entirely manual: cross-referencing device logs, related-asset telemetry, and historical patterns.

### 2b. Existing asynchronous mechanisms (used in isolation)

ICS standards include push-mode event mechanisms that reduce detection latency below the polling floor:

- **SNMP traps** (RFC 1215) — device emits a UDP message on state change.
- **DNP3 unsolicited responses** (IEEE 1815) — outstation pushes Class 1/2/3 events to the master without being polled, with millisecond-resolution device timestamps.
- **Syslog** — log-level event streaming.

These mechanisms are decades old. Industrial Historian and SCADA Master Station vendors selectively implement them. None of them, alone, produce semantic interpretation of the captured events.

### 2c. Existing LLM-augmented ICS efforts

Recent work pairs large language models with industrial systems for documentation summarization, alarm grouping, and post-incident root-cause investigation. To the inventor's knowledge, these systems operate on historical data with seconds-to-minutes latency after the operator has already received the alarm via conventional channels. They do not close the loop between sub-second device-initiated reporting and inline operator-facing AI interpretation.

### 2d. Gap in the prior art

The combination — sub-500ms device-initiated event capture **plus** sub-3-second LLM-generated root-cause narrative, integrated into a single operator workflow — is, to the inventor's knowledge, not present in any shipping ICS product or published research.

---

## 3. Summary of the invention

The invention is a system and method that combines:

(a) **An edge collector** running on premises with the monitored devices, configured to **passively receive** device-initiated event reports (DNP3 unsolicited responses, SNMP traps, syslog) on standard ICS protocols, with no requirement that the collector poll the devices first;

(b) **A semantic event-routing layer** that normalizes the captured events into a uniform schema (asset_id, metric, value, device-stamped timestamp, quality flags) regardless of source protocol;

(c) **A local alarm-evaluation engine** that applies operator-configured thresholds against the normalized events and produces alarm objects in milliseconds;

(d) **A latency tracker** that records (i) the latency from device-stamped event time to alarm generation, and (ii) the latency from alarm generation to root-cause narrative availability, exposing both as percentile histograms for evidence and operator-facing verification;

(e) **A cloud-side root-cause-analysis (RCA) service** triggered by critical alarms, which gathers contextual evidence (asset metadata, recent events on the same asset, related-asset state, historical telemetry) from a managed cloud datastore and invokes a large language model with a strict-schema prompt that constrains the model to a structured narrative — probable cause, evidence cited, severity, recommended action, confidence score — and never permits write-back to the field devices;

(f) **A safety interlock** ("IL-9000" in the implementation) ensuring the platform is read-only against PLC/RTU firmware. The interlock is enforced in code, not policy, and the LLM is explicitly instructed in its system prompt that any recommended action requiring a write must be deferred to a credentialed field technician.

(g) **A delivery channel** that publishes both the original alarm and the LLM-generated narrative onto the same MQTT topic hierarchy, so the operator dashboard renders both within seconds of the original physical event.

The combination produces a total visible latency from physical event to AI-generated root-cause narrative typically under four seconds — within the operator's attention window and orders of magnitude faster than conventional polling + manual investigation. The latency claims are independently measurable and recorded on every alarm path.

---

## 4. Brief description of drawings

(Placeholder — attorney to commission proper figures.)

- **Figure 1:** Conventional polling-only SCADA detection — pollers, threshold rules, alarm latency = poll interval.
- **Figure 2:** Aevus architecture — edge collector → asynchronous event receivers → local alarm engine → MQTT publisher → IoT Core → RCA Lambda → Bedrock → narrative publish → dashboard.
- **Figure 3:** Latency timeline comparing polling-only worst case (5s+) vs. invention (typically <500ms detection + <3s narrative).
- **Figure 4:** RCA Lambda flow — context gathering, prompt assembly, model invocation, response validation, dual write (MQTT publish + immutable S3 audit).
- **Figure 5:** Topic hierarchy (`aevus/<site>/<asset>/{telemetry,state,events,alerts,rca}/...`) showing IAM blast-radius scoping.

---

## 5. Detailed description

### 5a. Edge collector architecture

The edge collector executes on commodity industrial computing hardware (Raspberry Pi class or AWS IoT Greengrass-compatible) at the same network layer as the monitored devices. Three independent passive receivers run concurrently:

1. **SNMP trap receiver** binds UDP 162, decodes SNMPv2c trap PDUs, extracts source IP and varbinds, and maps each trap to a typed event with the source asset identified by IP-to-asset registry lookup.
2. **ICMP probe** issues per-second pings to every registered asset and emits state-transition events (up / degraded / down) on classification changes, distinguishing layer-3 reachability from application-layer agent state.
3. **DNP3 master** maintains a persistent TCP session to each Distributed Network Protocol outstation (typically port 20000), performs an integrity poll on connection establishment, and registers an unsolicited-response handler that captures Binary Input Change (G2) and Analog Input Change (G32) events with millisecond-resolution device timestamps.

Each receiver publishes normalized events onto an asyncio.Queue consumed by a single scheduler process. The scheduler converts the events into a uniform RawTelemetry → VitalSign → alarm-rule evaluation pipeline. Critically, the same threshold-rule store evaluates polled values and pushed events identically — the operator configures rules once.

The collector ALSO runs a polling layer (Modbus TCP, SNMP scrape) as a comprehensiveness fallback. The two paths converge at the alarm engine; whichever signal arrives first triggers the alarm.

### 5b. Comms-loss and partial-telemetry detection

The platform detects two failure modes orthogonal to threshold breach:

- **Communication loss (OFFLINE):** if no telemetry is received from an asset for N consecutive expected polls (configurable, default 3×), a comms-loss alarm fires. A staleness-sweep loop runs independently of the poll loop so a hung collector cannot suppress comms-loss alarms.
- **Partial telemetry:** if a successful poll returns a strict subset of the collector's declared `expected_metrics`, a warning-severity partial-telemetry alarm fires identifying the missing channels. Catches the failure mode where a device's SNMP/Modbus interface is up but one sensor channel has died.

The OFFLINE alarm auto-resolves when any signal (DNP3 unsolicited, SNMP trap, ICMP up, partial telemetry) confirms proof-of-life from the asset.

### 5c. Cloud routing and RCA invocation

The edge publisher writes each alarm and event to a canonical MQTT topic hierarchy:

```
aevus/{site_id}/{asset_id}/alerts/{severity}
aevus/{site_id}/{asset_id}/events/{class}
aevus/{site_id}/{asset_id}/telemetry/{metric}
aevus/{site_id}/{asset_id}/state/{key}
aevus/{site_id}/{asset_id}/rca/{alert_id}
```

A cloud-side topic rule routes the `alerts/critical` subtree to a serverless RCA function (AWS Lambda in the implementation; equivalent compute on other providers). The function:

1. Gathers context — recent events from an immutable audit store, asset metadata from an asset model service (AWS IoT SiteWise in the implementation), and related-asset state.
2. Renders a system prompt instructing the model that it is an ICS root-cause analyst constrained by ISA-101 (HMI design), IEC 62443 (industrial cybersecurity), NIST 800-82 (ICS security), and the IL-9000 read-only safety interlock.
3. Renders a user prompt assembling the alarm, asset, recent events, telemetry summary statistics, and related-asset state. The prompt requires the model to respond with a single JSON object matching a fixed schema and to cite evidence by timestamp / metric.
4. Invokes the language model (Claude via AWS Bedrock in the implementation).
5. Validates the response against the schema; rejects responses with out-of-range confidence, invalid severity, or missing keys.
6. Publishes the validated narrative to `aevus/{site_id}/{asset_id}/rca/{alert_id}` AND appends to the immutable audit store. Records the alert→narrative latency for the patent-evidence histogram.
7. On model failure, emits a deterministic fallback narrative so the audit trail is never blank.

### 5d. Operator delivery and verification

The operator dashboard subscribes via MQTT-over-WebSocket to `aevus/{site_id}/#`. Alarms appear in the alert list within milliseconds of MQTT publish. RCA narratives appear in a slide-up panel within seconds. Both render the alert→narrative latency as a visible badge — the operator sees the evidence inline.

The platform additionally exposes a metrics endpoint returning rolling percentile histograms of (i) device-to-alarm detection latency and (ii) alarm-to-narrative RCA latency, each annotated with the target threshold the platform claims to meet. The dashboard renders these as a live ticker; this becomes the operational evidence for the platform's latency claims.

### 5e. Safety enforcement (IL-9000)

The platform is read-only against PLC/RTU firmware by code, not by policy. All collector classes raise on any attempted write operation. The LLM is explicitly instructed in its system prompt that the platform is read-only and that any recommended action requiring a write must be deferred to a credentialed field technician. The interlock is enforced via a boolean constant `IL_009_ENFORCED = True` that no code path sets to False; code review for any commit touching firmware-relevant modules is gated on this invariant.

---

## 6. Draft claims (broad → narrow)

> **Note to attorney:** These are working-draft claims for negotiation. The independent claims target the combination of asynchronous device-initiated reporting + LLM reasoning + measured-latency evidence. Dependent claims narrow each subsystem.

### Independent claim 1 — system

A system for industrial control system monitoring, comprising:
(a) one or more edge collector processes executing on a computing device located on a network common to a plurality of monitored field devices, the edge collector processes each configured to passively receive device-initiated event reports from the field devices via at least one industrial control protocol that supports asynchronous event reporting;
(b) an event-normalization layer that produces, for each received event, a uniform representation including an asset identifier, a metric identifier, a numerical or boolean value, a device-stamped timestamp, and a quality indicator, the uniform representation being independent of the source protocol;
(c) a local alarm-evaluation engine executing on the same computing device, configured to apply operator-defined threshold rules to the uniform representations and to produce alarm objects within a target latency from the device-stamped timestamp;
(d) a latency-tracking subsystem that records detection latency between the device-stamped timestamp and alarm-object creation, and exposes percentile statistics of the recorded latencies;
(e) a publisher subsystem that emits alarm objects to a hierarchical message-bus topic;
(f) a remote root-cause analysis (RCA) service triggered by alarms of a designated severity, the RCA service configured to (i) gather contextual data including asset metadata and recent events for the alarm's asset from a persistent store, (ii) invoke a large language model with a system prompt declaring the system is read-only against the field devices and with a user prompt comprising the contextual data, (iii) validate the language model's response against a fixed structured-output schema, and (iv) emit the validated structured response to the same hierarchical message-bus topic;
(g) an RCA latency tracker that records latency between alarm-object creation and RCA structured-response emission;
(h) a safety interlock enforced in code that prevents the system from issuing any write operation to the field devices regardless of any recommendation the language model may produce.

### Independent claim 2 — method

A method for generating operator-facing root-cause narratives in an industrial control system, comprising:
(a) receiving, at an edge collector device, an unsolicited event report from a field device via DNP3, SNMP trap, or syslog;
(b) decoding the event report into a normalized representation comprising at least an asset identifier, metric, value, and device-stamped timestamp;
(c) applying operator-defined threshold rules to the normalized representation to produce an alarm object within 500 milliseconds of the device-stamped timestamp;
(d) recording the latency between the device-stamped timestamp and alarm creation in a rolling percentile histogram;
(e) publishing the alarm object to a topic hierarchy keyed by asset identifier and severity;
(f) on alarms of designated severity, invoking a serverless function that gathers contextual data and queries a large language model;
(g) constraining the language model via a system prompt enforcing the system's read-only safety posture and a strict JSON output schema;
(h) validating the language model output against the schema and publishing the structured narrative to the same topic hierarchy within 3 seconds of step (c);
(i) recording the alarm-to-narrative latency in a rolling percentile histogram;
(j) refusing, by enforcement in code rather than policy, any operation that would write to the field device regardless of the language model's recommendation.

### Dependent claims (selected)

**3.** The system of claim 1, wherein the industrial control protocol of (a) comprises at least DNP3 with unsolicited responses enabled, the unsolicited responses including device-stamped timestamps at millisecond resolution.

**4.** The system of claim 1, wherein the same threshold rules in (c) are applied identically to events received via the asynchronous protocols of (a) and to values obtained by a separate polling subsystem, such that the alarm engine is protocol-agnostic.

**5.** The system of claim 1, further comprising a partial-telemetry detection subsystem that compares the metrics actually emitted by a poll cycle against a per-collector declared expected-metrics set and generates a distinct alarm when a strict subset is returned while the device remains otherwise reachable.

**6.** The system of claim 1, further comprising a layer-3 reachability probe that emits up / degraded / down state transitions independently of any application-layer telemetry, such that the alarm engine can distinguish device-down from agent-down from network-path-down.

**7.** The system of claim 1, wherein the latency-tracking subsystem of (d) exposes the recorded statistics via an HTTP endpoint returning percentile metrics annotated with the platform's claimed target latency thresholds.

**8.** The system of claim 1, wherein the RCA service of (f) employs a fallback narrative path that produces a structurally identical but deterministic response when the language model invocation fails, such that the audit trail is never blank.

**9.** The system of claim 1, wherein the RCA service of (f) gathers contextual data from an immutable append-only store with retention configured for industrial cybersecurity audit compliance.

**10.** The method of claim 2, further comprising auto-resolving any open communication-loss alarm for the asset upon receipt of any asynchronous event report from that asset, thereby treating any asynchronous event as proof-of-life.

**11.** The method of claim 2, wherein the system prompt of (g) further enforces compliance with ISA-101 human-machine interface design principles and IEC 62443 industrial cybersecurity controls.

**12.** The system of claim 1, wherein the publisher of (e) and the dashboard subscriber consume the same hierarchical topic structure scoped per site and per asset, such that the alarm and the RCA narrative arrive on related topics readable by a single dashboard subscription pattern.

---

## 7. Abstract (~150 words)

A system and method for real-time industrial control system monitoring that combines asynchronous device-initiated event reporting (DNP3 unsolicited responses, SNMP traps, syslog) with large-language-model root-cause analysis. An edge collector passively receives event reports from field devices and applies operator-defined threshold rules locally to produce alarm objects within milliseconds of the device-stamped event timestamp. Alarms publish to a hierarchical message bus and trigger a remote serverless function that gathers contextual evidence and invokes a large language model under a strict-schema prompt constraining the model to a structured narrative — probable cause, cited evidence, severity, recommended action, confidence score — and explicitly declaring the platform read-only against field-device firmware. The structured narrative publishes to the same message bus within seconds of the original physical event, enabling operator interfaces to render both the alarm and the AI-generated root cause inline. Detection and root-cause-analysis latencies are recorded as percentile histograms and exposed for operational verification.

---

## 8. Evidence already on hand

For attorney review (and §132 declaration support if needed):

| Evidence | Location |
|---|---|
| Source code for edge collectors | `src/collectors/snmp_trap_receiver.py`, `icmp_probe.py`, `dnp3_unsolicited.py` |
| Source code for alarm engine | `src/engine/alert_engine.py` |
| Source code for latency tracker | `src/integrations/latency_tracker.py` |
| Source code for RCA Lambda | `infra/lambda/rca/handler.py`, `prompt.py`, `context.py` |
| Test suite proving operational correctness | `tests/` (217 tests passing) |
| Cloud architecture as IaC | `infra/terraform/` |
| Architecture documents | `docs/MONITORING_COVERAGE_PLAN.md`, `docs/AWS_LANDING_ZONE.md` |
| Operator runbook | `docs/OPERATOR_RUNBOOK.md` |
| Git commit history (priority-date proof) | `git log` on `claude/event-driven-edge-phases-1-7` — commits dated 2026-05-20, traceable to author + timestamp |
| Latency-claim instrumentation | `src/api/metrics.py` — `/api/v1/metrics/latency` endpoint with explicit target-threshold pass/fail |
| Synthetic alarm reproducibility | `scripts/inject_synthetic_alarm.py` + fixtures in `tests/lambda/fixtures/` |
| Patent-relevant brand & marketing | `~/Documents/IL/06_Products/Aevus_SCADA/PATENT_VALUATION_ANALYSIS.md`, `VIRTUAL_BOARD_PATENT_VALUATION_TEAM.md` |

---

## 9. Open questions for the attorney

1. **Claim scope** — should claim 1 be narrowed to specifically name DNP3 (the strongest protocol for the latency claim) or kept generic across all "asynchronous device-initiated reporting" to capture future protocols?
2. **Method vs system claims** — both included as drafted. Worth keeping both or focus filing on one to reduce examiner pushback?
3. **LLM vendor neutrality** — the implementation uses Claude via AWS Bedrock, but the claim is written model-agnostic. Defensible?
4. **Strict-schema-output claim** — should we file a separate claim covering the JSON-schema-constrained prompt + validation pattern? It's a genuine inventive step and may be reusable beyond ICS.
5. **Read-only safety interlock** — is this best treated as a dependent claim, or carved out as a separate filing? It's a meaningful safety/regulatory-posture invention in its own right.
6. **Prior-art search** — please run a targeted search against Schneider Electric, Honeywell, Emerson, ABB, Yokogawa, Rockwell, and Siemens patent portfolios for any recent (post-2022) ICS+LLM filings.
7. **PCT or US-only?** — Aevus's near-term market is US midstream + federal. Worth discussing whether a PCT filing makes sense for international option value.

---

## 10. Filing timeline (recommended)

| Step | Owner | Time |
|---|---|---|
| Dave reviews + redlines this draft | Dave | 1-2 days |
| Hand off to patent attorney (target: existing IL counsel) | Dave | day 3 |
| Attorney drafts §112-compliant provisional | Attorney | 2-3 weeks |
| Inventor + attorney review cycle | Both | 1 week |
| File USPTO provisional → priority date locked | Attorney | day 1 of file |
| 12-month window to file non-provisional | — | clock starts |

**Target filing date:** 30-45 days from today's capture. Anything longer and the protection window starts to compress against the natural product-development timeline.
