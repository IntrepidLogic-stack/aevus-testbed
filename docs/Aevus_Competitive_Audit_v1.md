# Aevus Competitive Audit — v1

**Prepared for:** Intrepid Logic LLC — Aevus product strategy
**Date:** 2026-05-27
**Status:** Internal strategy document. Not for external distribution.
**Scope:** Competitive landscape for AI-enhanced SCADA / industrial-data platforms targeting midstream oil & gas, with positioning recommendations for Aevus.

---

## 1. Executive Summary

Aevus is an AI-enhanced SCADA intelligence platform built edge-first on Raspberry Pi + AWS IoT Core, with Bedrock-driven root-cause-analysis (RCA) narratives, ISA-18.2 alarm hygiene, and an IL-9000 safety interlock that prohibits remote automated PLC firmware writes (patent-pending, P-008). The platform is pre-revenue, in lab testbed, and operates as an SDVOSB out of Katy, TX.

The midstream SCADA space is structurally **opaque on pricing**, **dominated by two incumbents** (AVEVA PI for historians, CygNet for midstream-specific SCADA), and **increasingly fragmented at the AI/analytics layer** (Cognite, Seeq, Honeywell Forge). Inductive Automation's **Ignition** is the only modern platform-level disruptor with broad traction. None of the five competitors examined here combine edge-first deployment, generative-AI RCA narratives, ISA-18.2 hygiene as first-class telemetry, and SDVOSB federal eligibility — which is the wedge Aevus should defend.

**Top three moves (90 days):** (1) ship a SiteWise asset-model bridge as the official "land path" off CygNet/PI, (2) productize ISA-18.2 hygiene as a standalone "Alarm Hygiene Score" module that can sit alongside an incumbent SCADA, and (3) close one paid pilot with a small midstream operator (under 50 RTUs) before chasing federal set-asides that depend on the still-pending SBA VetCert.

---

## 2. Aevus — Positioning Snapshot

| Attribute | Aevus |
|---|---|
| Architecture | Edge-first: Raspberry Pi collector + EC2 cloud + AWS IoT Core MQTT/TLS |
| Data plane | InfluxDB (time-series), SQLite (registry + audit), S3 (telemetry archive) |
| Protocols | SNMP v2c + traps, Modbus TCP, DNP3 (in test), ICMP |
| AI surface | Bedrock RCA Lambda (Haiku → Sonnet fallback) producing narrative root-cause |
| Alarm discipline | ISA-18.2: chattering detection, shelve/suppress, firmware-change events, maintenance-due |
| Safety posture | IL-9000 interlock — remote automated PLC firmware writes are structurally prohibited (patent P-008 provisional filed) |
| Health model | Composite: 35% comm reliability + 30% vital compliance + 20% predictive risk + 15% maintenance currency |
| Business posture | SDVOSB, Katy TX; SAM.gov + CAGE active; SBA VetCert resubmission in flight |
| Pricing posture (target) | Transparent, per-edge / per-site, no per-tag fees, no named-user fees |
| Status | Pre-revenue, live lab testbed (MikroTik + Cisco + Pi self-metrics under real SNMP); awards dashboard at aevus.intrepidlogic.io |

---

## 3. Competitor Selection — The Final Five

The five competitors below were selected to span the four ways an Aevus buyer could solve the problem instead:

1. **AVEVA PI System** — the default historian; "what we already have"
2. **Inductive Automation Ignition** — the modern platform challenger; "what we would replace it with"
3. **CygNet (Weatherford)** — the midstream-specific incumbent; "what midstream actually runs"
4. **Honeywell Forge** — the enterprise industrial-AI cloud; "what the CIO buys"
5. **Cognite Data Fusion** — the AI/analytics layer over existing OT; "what the digital team buys"

Considered and excluded: **Seeq** (strong but more downstream-process-analytics than midstream RTU); **Quorum** (gas-measurement focused, partially overlapping with CygNet); **GE Proficy / Emerson Plantweb / TrendMiner / Litmus / HighByte** (relevant but each occupies a narrower slice than the five above). HighByte and Litmus are noted as integration partners more than competitors.

---

## 4. Competitor Deep Dives

### 4.1 AVEVA PI System

**Snapshot.** AVEVA PI System (formerly OSIsoft PI, acquired by AVEVA in 2021; AVEVA itself was taken private by Schneider Electric in 2023) is the most widely deployed industrial historian in the world. Tens of thousands of installations across oil & gas, utilities, mining, and process manufacturing. AVEVA reports ~6,500 employees. PI System is now licensed under the **AVEVA Flex** subscription credit model rather than the legacy perpetual-per-tag scheme.

**Strengths.**
- Effectively the default historian — almost every large operator already runs it
- AF (Asset Framework) is the mature semantic model that downstream analytics depend on
- PI Vision, PI Integrator, and the AVEVA Connect cloud layer offer a polished BI surface
- Massive partner/SI ecosystem; AWS has explicit IMC reference architecture for PI → SiteWise
- Customer trust and reference base no startup can match in the short term

**Weaknesses / where Aevus can win.**
- Cost-per-tag economics scale poorly for small operators and edge sites — a 50-RTU midstream gathering system can pay disproportionate licensing for relatively few tags
- AI/RCA story is bolt-on (via AVEVA Connect / AVEVA Insight) and is generic predictive, not narrative
- ISA-18.2 alarm hygiene is delegated to third-party tools (AlarmWatch, PAS, etc.) — not native
- Deployment time is months, not days; nearly always implemented by SI partners
- No SDVOSB lineage; federal set-aside eligibility is irrelevant
- Vendor lock-in via AVEVA Flex credits is real and well-documented

**Pricing.** Not publicly published. Third-party industry estimates referenced commonly cite roughly **$20K+/yr for a 1,000-tag deployment and $90K+/yr for 10,000 tags with ~10 named users** under Flex. AVEVA's official posture is "contact sales." [SaaSWorthy estimate](https://www.saasworthy.com/product/pi-system/pricing), [TDengine pricing comparison](https://tdengine.com/pricing-comparison-tdengine-vs-pi-system/), [Canary Labs comparison](https://blog.canarylabs.com/canary-ignition-and-osisoft-pi-pricing-comparison). Treat all figures as directional — real pricing is account-by-account.

**Best ICP fit.** Large enterprise operators (super-majors, large independent pipelines) that already have AF deployed, have an existing SI relationship, and need historian-grade fidelity at very high tag counts. **Wrong fit:** small midstream operator with <100 RTUs, limited IT/OT staff, no incumbent SI.

---

### 4.2 Inductive Automation Ignition

**Snapshot.** Inductive Automation is privately held (Folsom, CA), ~600 employees. Ignition is a Java/Jython-based SCADA + HMI + IIoT platform that has grown rapidly on the back of an aggressive **unlimited-licensing** model. It is the most credible "modern SCADA" challenger to the legacy stack and has substantial midstream traction among operators rebuilding control rooms.

**Strengths.**
- **Unlimited tags, clients, and designers per server** — radically simpler economics than per-tag
- Strong Sparkplug B / MQTT support; first-class for IIoT and edge-of-network
- Active community, Ignition Exchange, modular architecture
- Perpetual-license option (rare in modern SCADA) with optional support
- Ignition Edge brings real SCADA capability to small hardware

**Weaknesses / where Aevus can win.**
- It is still a **platform**, not a product — buyers must design, build, and maintain the application themselves or hire an integrator
- No native generative-AI RCA narratives — analytics is a do-it-yourself layer
- ISA-18.2 alarm management is supported in principle but requires configuration and discipline; not enforced
- Java/Jython runtime is heavier than a Pi-class footprint at the true edge
- Not midstream-specific — no out-of-the-box CygNet-style gas-day, linepack, nominations models
- No SDVOSB lineage

**Pricing.** Inductive Automation publishes pricing publicly — a competitive differentiator. Base **Ignition Standard gateway starts around $1,200–$1,995 perpetual** with modules layered on top; full Ignition deployments commonly land in the **$10K–$60K range** depending on modules (Perspective, SQL Bridge, Reporting, OPC UA, etc.). Ignition Edge is much lower. Ignition Cloud Edition is consumption-priced. [Official pricing page](https://inductiveautomation.com/pricing/edition), [Ignition pricing PDF](https://s3.amazonaws.com/files.inductiveautomation.com/sellsheets/ignition_78/Ignition-HMI-SCADA-Pricing_en.pdf).

**Best ICP fit.** Operators with internal automation engineering depth who want to own their SCADA stack, want unlimited scale economics, and are comfortable building the application themselves or via a system integrator. **Wrong fit:** Aevus's natural ICP — small midstream ops with limited engineering bench who want product, not platform.

---

### 4.3 CygNet SCADA (Weatherford)

**Snapshot.** CygNet was developed in the 1990s specifically for upstream and midstream oil & gas; Weatherford acquired it in 2015. It is the industry's first **standardized SCADA solution** for oil & gas, with around **100 installations worldwide** processing over a billion transactions per day. Customers include super-majors, large independents, and major pipeline operators. In May 2024, Honeywell and Weatherford announced an emissions-management partnership built on CygNet. [Weatherford CygNet product page](https://www.weatherford.com/products-and-services/production-and-intervention/production-4-0/iot-scada-platform/), [Honeywell + CygNet emissions partnership](https://futurumgroup.com/insights/honeywell-and-cygnet-scada-partner-on-advanced-emissions-management/).

**Strengths.**
- Out-of-the-box oil & gas workflows: gas-day, linepack, contract nomination, energy load forecasting, measurement, well/route monitoring
- Deep entrenchment with large pipeline operators — high switching costs
- Standardized data model — collapses deployment time compared with a from-scratch SCADA build
- Honeywell partnership extends an emissions-reporting story that maps to federal reporting pressure

**Weaknesses / where Aevus can win.**
- CygNet is the canonical "incumbent stack" — expensive, legacy-architecture, heavy SI lift
- Limited AI/narrative analytics — the AWS IMC reference architecture explicitly exists to **export CygNet data to SiteWise** so other tools can analyze it. That is itself an Aevus opportunity.
- ISA-18.2 hygiene is bolt-on
- No SDVOSB lineage; federal set-aside math irrelevant
- Pricing fully opaque; deployments are six- and seven-figure projects

**Pricing.** Not published. CygNet is sold via Weatherford direct sales and named SI partners; deployments are typically multi-hundred-thousand-dollar to multi-million-dollar implementations including professional services. [Vendor reference](https://www.weatherford.com/documents/brochure/products-and-services/software/cygnet-scada-platform/).

**Best ICP fit.** Large midstream pipeline operators and gas marketers who need OOTB gas-day workflows and have the budget for a long, SI-led deployment. **Wrong fit:** small / new-build midstream operators, anyone trying to start cloud-native.

---

### 4.4 Honeywell Forge

**Snapshot.** Honeywell Forge is Honeywell's enterprise-scale operational-AI cloud, sold across industrials, buildings, aerospace, and energy. Honeywell (NASDAQ: HON, ~95,000 employees) positions Forge as an asset-performance-management and process-optimization layer that connects field operations to enterprise systems. For midstream, Forge slots above DCS/SCADA as the analytics + APM tier. [Honeywell Forge midstream page](https://process.honeywell.com/us/en/industries/oil_gas_hydrocarbons/pipelines-oil-gas).

**Strengths.**
- Enterprise credibility; the kind of brand the CIO/COO is already comfortable signing
- Asset-centric digital-operations model focused on energy, reliability, throughput
- Deep integration with Honeywell's installed Experion DCS base
- Backing of Honeywell's process-safety reputation

**Weaknesses / where Aevus can win.**
- Famously opaque pricing and long sales cycles ("no pricing page, no published rate card, no way to estimate TCO without engaging sales and often an implementation partner") — see [MachineCDN pricing analysis](https://www.machinecdn.com/blog/honeywell-forge-pricing-2026/)
- Best-fit when customer already has Experion / Honeywell hardware — friction otherwise
- AI narratives still tend toward dashboards + KPIs, not generative RCA
- Heavy lift for small operators — not a wedge product
- No SDVOSB posture

**Pricing.** Not published. Implementations consistently described as enterprise-class six- or seven-figure deals with required professional services.

**Best ICP fit.** Large midstream operators already in Honeywell's installed base, where Forge is the obvious upgrade path. **Wrong fit:** non-Honeywell shops, small operators, anyone trying to keep TCO predictable.

---

### 4.5 Cognite Data Fusion

**Snapshot.** Cognite (Oslo, Norway; ~700 employees; majority-owned by Aker ASA) sells **Cognite Data Fusion (CDF)** as an industrial DataOps platform that contextualizes OT, ET, and IT data into an enterprise knowledge graph. Strong oil & gas presence in Europe — Aker BP, OMV, and an SLB partnership. Primarily upstream/downstream, with growing midstream interest. [Cognite oil & gas page](https://www.cognite.com/en/industries/oil-and-gas), [OMV customer story](https://www.cognite.com/en/customers/omv).

**Strengths.**
- Best-in-class industrial knowledge graph and contextualization across PI / SAP / documents / 3D
- Strong AI/ML posture with productized "Cognite AI" agents
- Credible reference base in European super-majors
- DataOps philosophy is a real differentiator over historian-centric thinking

**Weaknesses / where Aevus can win.**
- Sits **above** the SCADA / RTU layer — does not replace it, requires it to already exist
- Pricing fully opaque; reportedly enterprise-class six- and seven-figure annual commitments
- Limited US midstream traction relative to upstream
- Edge story is partner-dependent, not native
- Not an alarm-hygiene tool — alarm rationalization is out of scope
- No SDVOSB posture

**Pricing.** Not published; custom-quoted. [SaaSWorthy notes](https://www.saasworthy.com/product/cognite-data-fusion/pricing) Cognite Data Fusion uses custom pricing with no free tier.

**Best ICP fit.** Operators with a serious digital-transformation budget who already have a historian and SCADA in place and want a contextualization + AI layer on top. **Wrong fit:** small midstream operator without an existing PI/CygNet base.

---

## 5. Head-to-Head Matrix — Aevus vs. The Field

Legend: Strong = clear native capability today; Partial = present but limited or bolt-on; Weak = not a credible part of the offering; Unknown = not disclosed publicly.

| Capability | Aevus | AVEVA PI | Ignition | CygNet | Honeywell Forge | Cognite |
|---|---|---|---|---|---|---|
| Generative-AI RCA narratives | **Strong** (Bedrock Haiku→Sonnet, narrative output) | Partial | Weak | Weak | Partial | Partial |
| ISA-18.2 alarm hygiene as native telemetry | **Strong** (chattering, shelve/suppress, firmware events) | Partial (3rd-party) | Partial (configurable) | Partial | Partial | Weak |
| Edge-first deployment (Pi-class footprint) | **Strong** | Weak | Partial (Ignition Edge) | Weak | Weak | Partial |
| Midstream-specific OOTB (gas-day, linepack, etc.) | Partial | Partial (via AF templates) | Weak (DIY) | **Strong** | Partial | Weak |
| SDVOSB federal set-aside eligibility | **Strong** (SAM/CAGE active; VetCert in resubmit) | Weak | Weak | Weak | Weak | Weak |
| MQTT → AWS IoT Core native | **Strong** | Partial (via IMC) | Strong (Sparkplug B) | Partial (via IMC) | Partial | Partial |
| Pricing transparency | **Strong** (target: published) | Weak | **Strong** | Weak | Weak | Weak |
| Time-to-deploy (first useful site) | Days | Months | Weeks | Months | Months | Months |
| Vendor lock-in risk | Low (AWS-native, open formats) | High (AF, Flex credits) | Low | High | High | High |
| ML / anomaly detection | Partial (Lookout for Equipment pilot) | Partial | Partial | Weak | Strong | **Strong** |
| Safety interlock against remote firmware writes (IL-9000) | **Strong (patent-pending P-008)** | Not a feature | Not a feature | Not a feature | Not a feature | Not applicable |
| Composite asset health score (OOTB) | **Strong** | Partial | Weak | Partial | Strong | Partial |

---

## 6. Analytical Personas (Internal Lenses)

> **Note: these personas are internal analytical lenses used to pressure-test strategy, not real-world expert opinions. They do not substitute for retained licensed counsel, CPAs, CISOs, or controls engineers. Any decision with legal, financial, regulatory, or safety consequence must be validated with a retained human professional before action.**

### 6.1 ICS / SCADA Engineer Lens
An operator running a SCADAPack 470 fleet over licensed-radio links cares about three things: **comm reliability, alarm noise floor, and the absence of surprises**. Aevus's composite health score (35% comm + 30% vitals + 20% predictive + 15% maintenance) maps directly to that mental model. The ISA-18.2 hygiene work — particularly chattering suppression and the shelve/unshelve audit log — is the thing they will instinctively trust, because that's where their actual day goes. The IL-9000 interlock (no remote firmware writes) reads as **adult engineering**, not a limitation: it's the kind of constraint a safety-conscious engineer wishes the rest of the industry would adopt. Ignition is the closest cultural fit at the platform level, but Ignition asks them to build. Aevus delivers.

### 6.2 Federal Contracts Lens
SDVOSB status is real and is the structural unfair advantage — once SBA VetCert resubmission clears (Task #65 in current planning, gated on Lynn's spousal disclaimer under 13 CFR 128). DHS SVIP and DOE pipeline-safety programs are realistic future opportunities **only after** that closes, and even then via Technical Calls under the next SVIP base solicitation (likely summer 2026). The federal pipeline-safety reporting tailwind (PHMSA 49 CFR 192/195) is real, but it is **not** a near-term revenue driver — treat it as a 12-to-18-month lane. **Do not** lead commercial conversations with "we're SDVOSB"; lead with the product, then disclose SDVOSB where set-aside eligibility actually matters.

### 6.3 CFO Lens
Three-year TCO for a small midstream operator (~50 RTUs, ~5,000 tags, modest user count) under each competitor, indicative ranges only:

| Option | 3-yr TCO (indicative, USD) | Hidden costs |
|---|---|---|
| AVEVA PI Flex | ~$200K–$400K | Tag growth, named users, SI hours, AF modeling time |
| Ignition | ~$50K–$150K | SI build cost (often 3–10x license), in-house automation engineer |
| CygNet | ~$500K–$2M+ | SI implementation, named-user fees, ongoing Weatherford services |
| Honeywell Forge | ~$500K–$2M+ | Sales-gated; expect Honeywell PS + partner PS |
| Cognite | ~$500K–$2M+ | Contextualization PS hours; rarely turnkey |
| Aevus (target) | ~$30K–$120K | Real edge hardware refresh; AWS run costs (predictable) |

These numbers are directional. The point is not the absolute figure — it is that **Aevus and Ignition are the only two options where a small operator can credibly predict their 3-year spend**, and Aevus is the only one of those two that ships product instead of platform.

### 6.4 CISO Lens
The IoT Core security posture (MQTT over TLS, AWS Device Defender Detect baseline live, Audit live, critical finding already remediated — Tasks #74-75 in the current backlog) is materially stronger than the typical midstream OT security baseline. The **IL-9000 interlock is a security feature, not just a safety feature**: it eliminates a category of attack — remote automated PLC firmware writes — by structural design rather than by policy. That is defensible against a frame where a CISO has to assume credentials will eventually be compromised. Frame this in security language ("structural mitigation of CWE-1326 / improper-authorization on firmware update paths") not just safety language.

### 6.5 Product Strategy Lens
The right wedge is **small-to-mid midstream operators (<100 RTUs) who currently run no historian or a barebones SCADA** — they are too small for PI, too non-Honeywell for Forge, too thin-staffed for Ignition, and not the right ICP for Cognite. CygNet is the only real incumbent threat in that segment, and its deployment friction and pricing opacity make it beatable. **Do not** wedge head-on against PI or CygNet in their installed base — instead, position Aevus as the **complementary alarm-hygiene + AI RCA layer** that runs alongside an existing CygNet/PI environment via the AWS IMC pattern. That is a much easier first sale.

### 6.6 Buyer Lens (Operations VP at a small midstream operator)
This person does not want to learn a new SCADA philosophy. They want fewer 3 a.m. calls, fewer truck rolls, and a defensible answer when PHMSA asks. The pitch that lands is: "Keep your existing SCADA. Put a Pi at the site. In two weeks you'll get an AI-written root-cause email every time something fails, a chattering-alarm score per asset, and a maintenance-due ledger. Fixed monthly price. If it doesn't pay back, turn it off."

---

## 7. Top Recommendations — Next 90 Days

### Rec 1 — Ship a CygNet/PI → SiteWise bridge as the official "land" motion
The AWS Industrial Machine Connectivity (IMC) pattern already exists and is publicly documented. Productize Aevus's side of it: a deterministic mapping from CygNet/PI asset hierarchies into the SiteWise asset model that Aevus already consumes. This converts the dominant install base from a competitor into **a feed**. The first sale becomes "we run alongside what you have," not "rip and replace." [Reference architecture](https://d1.awsstatic.com/architecture-diagrams/ArchitectureDiagrams/cygnet-and-pi-data-to-sitewise-ra.pdf).

### Rec 2 — Productize "Alarm Hygiene Score" as a standalone module
Aevus already has ISA-18.2 chattering detection, shelve/suppress with audit trail, firmware-change events, and maintenance-due logic live in the AlertEngine. Bundle these into a standalone "Aevus Alarm Hygiene" SKU that can be sold to a CygNet/PI shop **without replacing their SCADA**. This is the easiest possible first paid pilot — low integration risk, immediate operator value, clean metric (alarm-rate reduction %).

### Rec 3 — Close one paid pilot with a sub-100-RTU midstream operator
Stop optimizing for federal opportunities that depend on SBA VetCert resubmission. The federal lane is real but slow. The commercial lane is faster, smaller-ticket, and produces the reference customer that everything downstream depends on. Target a Texas or Oklahoma small midstream operator. Price the pilot at $15K–$30K for a 90-day proof against one compressor station. The deliverable is a real RCA narrative for a real incident plus a chattering-alarm reduction number.

### Rec 4 — Publish pricing
None of the five competitors do. This is a costless differentiator. Even a posted starting price ("Aevus Edge — $X/site/month, includes Pi collector firmware, MQTT/TLS, AI RCA, ISA-18.2 hygiene") removes the largest single point of friction in OT software sales. Inductive Automation has demonstrated this works at scale.

### Rec 5 — Frame IL-9000 in security language, not only safety language
Pitch the IL-9000 interlock to CISOs as a structural mitigation against compromised-credential firmware-write attacks. The patent P-008 provisional gives this defensible language. This widens the buyer set from "ops VP only" to "ops VP plus CISO," which is exactly the buying coalition needed to clear procurement at a midstream operator.

---

## 8. Risk Notes

- **Bedrock dependency.** Aevus's RCA narrative is the headline AI feature and currently single-sourced to AWS Bedrock. The Haiku→Sonnet fallback chain mitigates within-AWS, but a multi-region or multi-provider fallback should be on the roadmap before any enterprise sale.
- **Patent posture.** P-008 is provisional. Treat it as marketing-grade defensibility, not legal-grade, until non-provisional conversion. Validate any patent-related claim with real outside counsel before external use.
- **Federal status accuracy.** SAM.gov + CAGE are live. SBA VetCert is in resubmission. **Do not** claim VetCert-conditional set-aside eligibility in marketing until the resubmission clears.
- **Pricing claims for competitors.** Every figure in this document for AVEVA, CygNet, Honeywell, and Cognite is directional. Real numbers in this market are deal-specific and NDA-bound. Cite ranges, not points, externally.

---

## 9. Sources

- AVEVA PI System: [Official product page](https://www.aveva.com/en/products/aveva-pi-system/), [SaaSWorthy pricing](https://www.saasworthy.com/product/pi-system/pricing), [TDengine pricing comparison](https://tdengine.com/pricing-comparison-tdengine-vs-pi-system/), [Canary Labs comparison](https://blog.canarylabs.com/canary-ignition-and-osisoft-pi-pricing-comparison)
- Inductive Automation Ignition: [Pricing page](https://inductiveautomation.com/pricing/edition), [Unlimited licensing page](https://inductiveautomation.com/ignition/unlimited), [Ignition pricing sheet PDF](https://s3.amazonaws.com/files.inductiveautomation.com/sellsheets/ignition_78/Ignition-HMI-SCADA-Pricing_en.pdf)
- CygNet (Weatherford): [Product page](https://www.weatherford.com/products-and-services/production-and-intervention/production-4-0/iot-scada-platform/), [Brochure PDF](https://www.weatherford.com/documents/brochure/products-and-services/software/cygnet-scada-platform/), [Honeywell + CygNet emissions partnership](https://futurumgroup.com/insights/honeywell-and-cygnet-scada-partner-on-advanced-emissions-management/)
- Honeywell Forge: [Midstream pipelines page](https://process.honeywell.com/us/en/industries/oil_gas_hydrocarbons/pipelines-oil-gas), [MachineCDN pricing analysis](https://www.machinecdn.com/blog/honeywell-forge-pricing-2026/), [Honeywell Forge overview](https://www.honeywell.com/us/en/solutions/honeywell-forge)
- Cognite Data Fusion: [Oil & gas page](https://www.cognite.com/en/industries/oil-and-gas), [CDF product page](https://www.cognite.com/en/product/cognite_data_fusion_industrial_dataops_platform), [OMV customer story](https://www.cognite.com/en/customers/omv), [SaaSWorthy pricing](https://www.saasworthy.com/product/cognite-data-fusion/pricing)
- AWS context: [IMC for Energy blog](https://aws.amazon.com/blogs/industries/aws-industrial-machine-connectivity-imc-for-energy-at-bpx/), [CygNet/PI → SiteWise reference architecture PDF](https://d1.awsstatic.com/architecture-diagrams/ArchitectureDiagrams/cygnet-and-pi-data-to-sitewise-ra.pdf), [AWS IoT SiteWise overview](https://aws.amazon.com/iot-sitewise/)
- ISA-18.2 context: [PcVue ISA-18.2 paper](https://www.pcvue.com/resource/pcvue-scada-compliance-with-isa-18-2-alarm-management-standard-2/), [Yokogawa ISA-18.2 implementation](https://www.yokogawa.com/us/library/resources/media-publications/implementing-alarm-management-per-the-ansi-isa-182-standard-control-engineering/)
- Market sizing: [Grand View Research oil & gas SCADA market](https://www.grandviewresearch.com/industry-analysis/oil-gas-scada-market-report)

---

*End of document. Version 1.0 — 2026-05-27. Maintained at `Documents/IL/06_Products/Aevus_SCADA/AEVUS_filesv2/testbed-kit/docs/Aevus_Competitive_Audit_v1.md`.*
