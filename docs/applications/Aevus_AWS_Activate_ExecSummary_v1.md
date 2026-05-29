# Aevus — Executive Summary

**For:** AWS Activate Portfolio resubmission
**Company:** Intrepid Logic LLC (SDVOSB, Katy TX) — SAM.gov registered, CAGE active
**Product:** Aevus — AI-enhanced SCADA intelligence platform for midstream oil & gas
**Date:** 2026-05-27
**Status:** Pre-revenue · Live lab testbed · Patent provisional P-008 filed

---

## What Aevus is

Aevus is an **edge-first SCADA intelligence platform** that turns commodity Raspberry Pi hardware plus AWS IoT Core into a production-grade industrial monitoring stack — with **AI-generated root-cause narratives** (AWS Bedrock, Haiku→Sonnet fallback) and **ISA-18.2 alarm hygiene** baked in as first-class telemetry.

Built natively on AWS: IoT Core (MQTT/TLS), Bedrock, Lambda, SiteWise-ready, S3 archive, CloudWatch ops, IoT Device Defender hardened. Pi edge collectors run real SNMP/Modbus polling today against MikroTik routers, Cisco switches, Trio JR900 radios, and SCADAPack 470 RTUs.

## The market gap

Midstream oil & gas runs on two opaque incumbents — **AVEVA PI** (historians, per-tag licensing, ~$20K–$90K+/yr for typical deployments) and **CygNet by Weatherford** (midstream-specific SCADA, no public pricing, multi-month SI implementations). The modern challenger, **Inductive Automation Ignition** ($10K–$60K), is a platform requiring buyers to build their own application. The AI/analytics layer (Cognite, Honeywell Forge, Seeq) is bolt-on, generic-predictive, and enterprise-priced.

**None of the five top competitors combine** edge-first deployment, generative-AI root-cause narratives, ISA-18.2 alarm hygiene as native telemetry, and SDVOSB federal eligibility. That intersection is Aevus's wedge.

## Differentiation (verified in lab)

| Capability | Status |
|---|---|
| AI RCA narratives (Bedrock multi-model fallback) | ✅ Live |
| ISA-18.2 chattering detection + shelve/suppress audit | ✅ Live in AlertEngine |
| Firmware-change + maintenance-due event tracking | ✅ Live, SQLite-persisted |
| **IL-9000 safety interlock** — PLC firmware writes structurally prohibited remotely (Patent P-008 provisional) | ✅ Enforced by code, never policy |
| Edge-first: Pi → MQTT-TLS → IoT Core | ✅ Live, awards dashboard at aevus.intrepidlogic.io |
| Composite health score (35% comm + 30% vitals + 20% predictive + 15% maintenance) | ✅ Live |
| MQTT-over-WSS dashboard transport, Cognito Identity Pool | ✅ Wired |
| IoT Device Defender Detect baseline + Audit | ✅ Live, critical finding remediated |

## Traction

- **Live testbed:** 7 lab assets under continuous real polling (MikroTik L009, Cisco Catalyst 2960, Pi self-metrics) + 4 simulator collectors (radios + RTU pending site visit)
- **Patent:** P-008 provisional filed; reduction-to-practice evidence archived to S3 with checksum
- **Infra:** CloudTrail enabled, 13 CloudWatch alarms, Lambda IaC, SNS critical-alert path verified end-to-end, SES HTML branded alerts live
- **Compliance:** ISA-18.2-grounded alarm catalog (`AEVUS_ALARM_CATALOG_v1.md`) published; firmware tracker, maintenance tracker, shelve audit with REST endpoints

## Go-to-market — next 90 days

1. **Land path:** ship CygNet/PI → SiteWise asset-model bridge so first sale is "run alongside what you have," not rip-and-replace
2. **Standalone SKU:** productize ISA-18.2 hygiene as "Alarm Hygiene Score" — sellable to a PI/CygNet shop without displacing them
3. **First paid pilot:** close one sub-100-RTU midstream operator (TX/OK), $15K–$30K, 90 days, one compressor station
4. **Pricing transparency:** publish per-edge / per-site pricing — none of the 5 competitors do, costless differentiator

## AWS Activate ask

Portfolio-tier credits to underwrite the IoT Core ingestion, Bedrock RCA inference, and Device Defender continuous-monitoring costs through first paid pilot and reference customer. Intrepid Logic is committed to AWS as the cloud backbone — every component (IoT Core, Bedrock, SiteWise, Lambda, S3, CloudWatch, Cognito, SES) is already wired.

**Real defensible credit ask total:** ~$100–105K (cross-checked against `il-credit-tracker.md`).
