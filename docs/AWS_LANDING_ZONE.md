# Aevus AWS Landing Zone

**Status:** Draft for review
**Last updated:** 2026-05-20
**Author:** Dave Spencer / Claude
**Scope:** AWS architecture for the Aevus SCADA platform — edge runtime, cloud ingestion, asset modeling, AI, and compliance. Companion to `MONITORING_COVERAGE_PLAN.md`.
**References:** `~/.claude/projects/.../memory/il_deployment_playbook.md`, `~/Documents/IL/06_Products/Aevus_SCADA/Aevus_AWS_Reference_Architecture.docx`.

**Approved execution sequence (Dave, 2026-05-20):**
1. Local Python first for coverage Phases 1–3 (trap receiver, ICMP probe, DNP3 unsolicited).
2. Greengrass v2 wrap — same code, managed runtime.
3. IoT Core MQTT + SiteWise — cloud landing zone; dashboard moves to MQTT-over-WSS.
4. Bedrock for AI RCA; pilot SiteWise L4E for vibration anomaly.
5. Defer IoT Events.

---

## 1. Design principles

1. **Edge keeps sub-second alarming.** WAN loss is normal in midstream. Any alarm that requires the cloud to evaluate is a non-starter. DNP3 unsolicited, SNMP traps, ICMP, and threshold rules all evaluate on the Greengrass core.
2. **Cloud holds the fleet view, the model, the AI, and the audit.** Asset hierarchy, cross-asset correlation, ML inference, and tamper-evident audit logs run in AWS.
3. **No telemetry duplication.** One canonical home per data class. Asset properties → SiteWise. Raw time-series → Timestream-for-InfluxDB (preserves our InfluxQL). Events → S3 Object Lock + CloudWatch Logs. Configs → S3 encrypted bucket.
4. **IaC for everything.** Terraform per the IL deployment playbook. No console-clicked resources in production.
5. **Least privilege end-to-end.** Each Greengrass component, each Lambda, each user gets its own IAM role. No shared `il-admin` credentials in runtime paths.
6. **Federal-ready by default.** GovCloud-compatible service choices. CloudTrail + Config + Security Hub from day one. No service that lacks a FedRAMP equivalent.

---

## 2. Topology

```
┌──────────────────── REMOTE SITE (compressor station, pump pad, lab) ────────────────────┐
│                                                                                          │
│   [JR900 Radio]──┐                                                                       │
│                  ├──→ [Cisco 2960]──→ [MikroTik L009]──→ WAN ──→ AWS                     │
│   [SCADAPack]────┤                              ▲                                        │
│   [UPS]──────────┤                              │                                        │
│                  ▼                              │                                        │
│           [Raspberry Pi / Greengrass core]──────┘                                        │
│            • SNMP poller / trap receiver (UDP 162)                                       │
│            • Modbus poller / DNP3 master (TCP 502 / 20000)                               │
│            • ICMP probe                                                                  │
│            • Syslog receiver (UDP 514)                                                   │
│            • Local alert engine + threshold rules                                        │
│            • Store-and-forward buffer (SQLite spool)                                     │
│            • Publishes to AWS IoT Core via MQTT-over-TLS                                 │
│                                                                                          │
│   [Uplogix 5000]──→ separate OOB path ──→ AWS (cellular or alt path)                     │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────── AWS (us-east-2 primary) ──────────────────────────────┐
│                                                                                          │
│   AWS IoT Core (MQTT broker)                                                             │
│     ├─ Rule: events       → Lambda(routeAlarm) → SNS / SQS / Bedrock                    │
│     ├─ Rule: state        → IoT SiteWise asset properties                                │
│     ├─ Rule: telemetry    → Timestream / S3 (raw retention)                              │
│     └─ Rule: audit        → S3 (Object Lock)                                             │
│                                                                                          │
│   IoT SiteWise (asset model: site → cabinet → device → property)                         │
│     ├─ Asset types: radio, rtu, switch, router, ups, sensor                              │
│     ├─ Alarm model: threshold + state-based                                              │
│     └─ Lookout for Equipment (L4E) — anomaly models on vibration / RF                    │
│                                                                                          │
│   Bedrock (Claude Sonnet/Haiku) — invoked by Lambda on critical events for RCA narrative │
│                                                                                          │
│   Dashboard (CloudFront + S3 static SPA) ──→ AppSync GraphQL subs OR direct MQTT-WSS     │
│   API (FastAPI on ECS Fargate behind ALB) — REST control plane, acknowledgments         │
│   RDS / Aurora (PostgreSQL) — asset registry, alert log, user accounts                   │
│                                                                                          │
│   CloudTrail (control plane) + AWS Config + Security Hub + GuardDuty                     │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Edge — Greengrass v2 components

Each existing Python collector becomes a Greengrass component. Same code, packaged with a recipe. Deployment is fleet-wide via Greengrass deployments — `git push` triggers a build that publishes new component versions and rolls them out per the deployment configuration (canary first, then full fleet).

| Component | Purpose | Recipe notes |
|---|---|---|
| `io.intrepid.aevus.poller-snmp` | SNMP polling of radios + network gear | needs `pysnmp`; reads SNMP community from Secrets Manager |
| `io.intrepid.aevus.poller-modbus` | Modbus TCP poll of SCADAPack | `pymodbus` |
| `io.intrepid.aevus.collector-dnp3` | DNP3 master for SCADAPack unsolicited | `opendnp3` (TBD pending spike) |
| `io.intrepid.aevus.trap-receiver` | UDP 162 SNMP trap listener | needs `CAP_NET_BIND_SERVICE` |
| `io.intrepid.aevus.icmp-probe` | 1s ICMP probe of all assets | needs `CAP_NET_RAW` |
| `io.intrepid.aevus.syslog-receiver` | UDP 514 syslog listener | needs `CAP_NET_BIND_SERVICE` |
| `io.intrepid.aevus.alert-engine` | Local threshold + comms-loss + partial-telemetry evaluation | uses asset registry from local SQLite cache |
| `io.intrepid.aevus.publisher` | Batches local events and publishes to IoT Core MQTT | handles store-and-forward when WAN down |
| `io.intrepid.aevus.config-drift` | Periodic config hash diff for network gear | runs on schedule |
| `aws.greengrass.StreamManager` | AWS-supplied store-and-forward buffer | configured for `aevus/*` streams |
| `aws.greengrass.SecureTunneling` | Remote access to the Pi for troubleshooting | replaces RustDesk for production |

**Local store-and-forward:** Stream Manager + SQLite spool. Targets 7 days of buffered telemetry if WAN is down. Events drain in order on reconnect; alarms are deduplicated by `(asset_id, key, detected_at)`.

**OTA updates:** signed component artifacts in S3. Rollback by redeploying the prior version — automatic if a canary device fails health check.

---

## 4. Cloud — IoT Core topic hierarchy

```
aevus/{site_id}/{asset_id}/telemetry/{metric}         — raw values (5s/30s cadence)
aevus/{site_id}/{asset_id}/state/{key}                — discrete state (reachability, oob, status)
aevus/{site_id}/{asset_id}/events/{class}             — discrete events (snmp-trap, dnp3, syslog, drift)
aevus/{site_id}/{asset_id}/alerts/{severity}          — alarm engine output
aevus/{site_id}/{asset_id}/ops/heartbeat              — collector liveness (1s)
aevus/{site_id}/system/audit                          — site-wide audit feed
```

**Topic-level IAM.** Each Greengrass core can only publish under its own `{site_id}/` prefix. Each operator MQTT subscription is policy-restricted to sites they're authorized for.

**IoT Core rules** route topics to the right destination:

| Topic pattern | Rule action | Destination |
|---|---|---|
| `aevus/+/+/telemetry/+` | Timestream PUT + SiteWise property update | Time-series + asset model |
| `aevus/+/+/state/+` | SiteWise property update | Asset model |
| `aevus/+/+/events/+` | Lambda → route by severity | Alarm router |
| `aevus/+/+/alerts/critical` | Lambda → Bedrock RCA, then SNS | Operator paging |
| `aevus/+/+/alerts/+` | DynamoDB PUT (alert log) | Alert log |
| `aevus/+/system/audit` | S3 PUT with Object Lock | Compliance audit log |

---

## 5. SiteWise asset model

```
Site (e.g. "Lab Cabinet" / "Compressor Station 14")
└── Cabinet
    ├── Radio (asset model: TrioJR900)
    │   ├── property: rssi (dBm)
    │   ├── property: snr (dB)
    │   ├── property: temperature (°C)
    │   ├── property: voltage (V)
    │   └── alarm:    comm_loss, rssi_low, temp_high
    ├── RTU (asset model: SCADAPack470)
    │   ├── property: suction_pressure (PSI)
    │   ├── property: discharge_pressure (PSI)
    │   ├── property: battery_voltage (VDC)
    │   ├── property: vibration (mm/s)
    │   └── alarm:    comm_loss, high_pressure, low_battery, comm_fault, partial_telemetry
    ├── Switch (asset model: CiscoCatalyst2960)
    │   └── property: cpu_load, memory_usage, link_status
    └── Router (asset model: MikroTikL009)
        └── property: cpu_load, memory_usage, link_status
```

**Why SiteWise and not just RDS:** SiteWise's asset model handles hierarchy and transforms natively (e.g. "RSSI delta over last 5 min" as a computed property), and its alarm model integrates with EventBridge. For a single-site lab this is overkill; for the fleet-of-50-sites target it's essential.

---

## 6. AI — Bedrock + L4E split

| Use case | Engine | Why |
|---|---|---|
| Root-cause narrative ("Why did asset X alarm?") | **Bedrock — Claude Sonnet/Haiku** | Reasoning over heterogeneous evidence (events + time-series + asset metadata). Per IL global rule. |
| Vibration / RF anomaly detection (continuous) | **SiteWise Lookout for Equipment (L4E)** | Purpose-trained on industrial signals. Faster + cheaper than running an LLM continuously. Outputs feed back into Bedrock as evidence. |
| Predictive failure horizon ("3 days") | **SageMaker** (custom model on labeled data) | Existing `src/engine/prediction.py` migrates here once we have enough labeled data. |
| Operator chat ("show me everything weird about this asset") | **Bedrock — Claude Sonnet** | Same model as RCA, different prompt. |

**Patent positioning (P-008):** the *combination* of DNP3 unsolicited millisecond events + L4E continuous anomaly detection + Bedrock RCA narrative is the defensible claim. Each individually exists; the integrated real-time loop is the invention.

---

## 7. Networking & security

- **MQTT-over-TLS 1.2/1.3** with X.509 mutual auth. Each Greengrass core has its own cert provisioned by IoT Core fleet provisioning.
- **No inbound from the internet to the edge.** All connections initiated outbound from the Pi.
- **VPC** for ECS/RDS/AppSync. Public-facing only the CloudFront distribution and the IoT Core endpoint (managed by AWS).
- **Secrets Manager** for SNMP community strings, DNP3 master credentials, any RTU passwords. Greengrass components retrieve at component start.
- **KMS-managed keys** for S3, RDS, Timestream, SiteWise. Customer-managed (not AWS-managed) for federal pursuits.
- **CloudTrail** all regions, log file validation enabled, delivered to a dedicated audit account once we move to multi-account.
- **AWS Config** with conformance pack for NIST 800-53 + IEC 62443 controls where AWS-defined.
- **Security Hub + GuardDuty** for continuous threat monitoring.

---

## 8. Account & IAM

Per IL deployment playbook:

- **Today:** stay in account `676433090238`, tagged `product=aevus, env=dev`.
- **Trigger to split:** first paying customer pilot or first federal contract pursuit, whichever comes first. At that point move to AWS Organizations:
  - `il-management` (billing, IAM Identity Center, CloudTrail aggregation)
  - `il-shared-services` (Route 53, ACM, shared S3)
  - `aevus-prod`, `aevus-dev` (workload accounts)
- **GitHub Actions deploys** via OIDC (no static AWS keys in GitHub).
- **Operator access** via IAM Identity Center → permission sets. No long-lived users in workload accounts.

---

## 9. Cost model

Lab scale (6 devices, 5s/30s polling, ~5K events/day):

| Service | Estimated monthly | Notes |
|---|---|---|
| IoT Core | <$5 | per-million-message pricing |
| Greengrass v2 | $0 | first 1,000 devices free |
| SiteWise | <$20 | per-property pricing dominates |
| Timestream-for-InfluxDB | ~$50 | small instance, can use serverless tier |
| Lambda + Bedrock | <$10 | sparse invocations |
| S3 (audit + raw) | <$5 | Object Lock storage |
| CloudFront + S3 dashboard | <$2 | |
| ECS Fargate (FastAPI) | ~$30 | smallest task config |
| RDS Aurora Serverless v2 | ~$45 | min 0.5 ACU |
| CloudTrail / Config / Security Hub / GuardDuty | ~$30 | baseline cost regardless of usage |
| **Total** | **~$200/mo** | covered by AWS Activate credits |

Production midstream pilot (50 sites, ~500 devices, ~1M events/day): scale ~10×. Still well within early-stage budgets.

---

## 10. Open architectural questions

1. **Region.** us-east-2 (Ohio) vs us-west-2 (Oregon) primary. us-east-2 is closer to Texas operations; us-west-2 has more SCADA reference customers and Bedrock model availability. Recommend us-east-2 for latency, us-west-2 second region for DR.
2. **MQTT-WSS vs AppSync subscriptions** for the dashboard. MQTT-WSS is simpler and matches the data model; AppSync gives us GraphQL ergonomics and managed auth. Recommend MQTT-WSS initially, AppSync later if dashboard query complexity grows.
3. **DNP3 library on Greengrass.** `opendnp3` (mature, C++ bindings) vs `dnp3-python` (lighter, less proven). Need a spike on the Pi.
4. **L4E training data.** Lookout for Equipment needs labeled data we don't have yet. Bootstrap with simulator + lab readings, refine with real customer data after first pilot.
5. **GovCloud parity.** Bedrock model availability in GovCloud lags commercial. If federal pursuit comes first, may need a hybrid pattern (commercial Bedrock for inference, GovCloud for storage / control plane).
6. **IL multi-product convergence.** Signal Storm, Watchman, JATO Advisor, and reIGNIT all eventually want a similar telemetry pattern. Worth deciding now whether `io.intrepid.*` Greengrass components and IoT Core topic patterns are Aevus-only or IL-wide.

---

## 11. Action items

1. **AWS Activate credit check** — see `AWS_ACTIVATE_CREDITS_CHECK.md`. Block any spend until confirmed.
2. **Spike: DNP3 library choice** on the Pi. Half day.
3. **Stand up minimal Greengrass v2 + IoT Core in `676433090238`.** Register the Pi as a core device, publish a single hello-world message. 1 day.
4. **Define SiteWise asset model** in Terraform under `infra/terraform/aws-sitewise.tf`. Mirror the structure in §5. 1 day.
5. **First component refactor** — pick `icmp-probe` (smallest collector) as the migration trial. 1 day.
6. **CloudTrail + S3 Object Lock audit bucket** — set up before any production events flow. Half day.
7. **Bedrock RCA Lambda prototype** — once Phase 3 (DNP3) lands locally, this becomes the cloud demo of the patent claim. 1.5 days.
