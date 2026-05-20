# AWS Activate Application — Draft Answers

Paste-ready responses for the AWS Activate portal questionnaire, the AWS Public Sector SDVOSB pathway application, and the NVIDIA Inception application.

**Submission order (recommended):**
1. AWS Activate Founders tier (self-serve, 24-48h approval) — §1
2. NVIDIA Inception (runs in parallel, ~1 week) — §3
3. AWS Public Sector SDVOSB pathway (reviewed by humans, ~2 weeks) — §2

Dave applies all three. Activate Portfolio tier upgrade goes through the AWS Public Sector route, so submitting §1 first then escalating via §2 is the cleanest path.

---

## 1. AWS Activate portal questionnaire

URL: https://aws.amazon.com/activate/

### Company name
Intrepid Logic LLC

### Company website
intrepidlogic.io

### Country
United States

### State
Texas

### City
Katy

### Year founded
2025 (verify against state-of-formation cert)

### Company size
1–10 employees

### Funding stage
Pre-seed / bootstrapped / SDVOSB

### Are you incorporated as a startup?
Yes — Intrepid Logic LLC is a Service-Disabled Veteran-Owned Small Business (SDVOSB).

### What does your company do? (description, ~150 words)
Intrepid Logic is a Service-Disabled Veteran-Owned Small Business (SDVOSB) building AI-native industrial software. Our flagship product Aevus is an AI-enhanced SCADA platform for midstream oil & gas operators — it ingests telemetry from radios, RTUs, and process sensors at remote sites, detects events in milliseconds via DNP3 unsolicited responses and SNMP traps, and uses AWS Bedrock to generate real-time root-cause narratives for control-room operators. The architecture is edge-first (AWS IoT Greengrass on Raspberry Pi collectors) with a cloud landing zone on AWS IoT Core, SiteWise, Bedrock, and Lookout for Equipment. We have nine products in development under one corporate umbrella, ranging from emergency volunteer coordination (Signal Storm) to consumer AI (K9 Pet Health) to additive manufacturing intelligence (3Degz). All products share an AWS-native infrastructure baseline.

### What stage is your product in?
Pre-revenue / building testbed against physical lab hardware. Aevus has 200+ tests passing, complete event-driven edge architecture, and an AWS landing zone deployable via Terraform. Currently provisioning lab hardware and pursuing first pilot deployments with midstream operators.

### Which AWS services do you plan to use?
- AWS IoT Core (MQTT broker, X.509 mutual auth)
- AWS IoT Greengrass v2 (edge runtime on Raspberry Pi)
- AWS IoT SiteWise (industrial asset model + alarms)
- Amazon Lookout for Equipment (predictive maintenance)
- AWS Bedrock (Claude models for root-cause inference)
- AWS Lambda (event-driven RCA + scheduled inference forwarding)
- Amazon S3 with Object Lock (compliance audit trail)
- Amazon Timestream for InfluxDB (time-series telemetry)
- Amazon RDS Aurora Serverless (asset registry + alert log)
- AWS CloudTrail + Config + Security Hub (audit + compliance posture)
- Amazon Cognito (dashboard auth)
- AWS KMS (customer-managed encryption keys for federal-readiness)
- Amazon ECS Fargate (FastAPI control plane)
- Amazon CloudFront + S3 (static dashboard hosting)

### Estimated monthly AWS spend (current → 6 months → 12 months)
- Now: $0 (pre-deployment)
- 6 months (single lab + 2-3 pilot sites): ~$400/mo
- 12 months (10 production sites): ~$2,500/mo

These projections fit comfortably under any Activate tier credit pool.

### Are you a customer of AWS Marketplace, AWS Activate Partner, or Anthropic for Bedrock?
- Bedrock (Anthropic models): planned primary consumer for our RCA inference pipeline. The combination of DNP3 unsolicited millisecond-latency events with Claude Sonnet-grade reasoning is the patentable invention behind P-008.

### Any AWS contacts?
(Fill in if Dave has any. Otherwise leave blank — the SDVOSB pathway in §2 gets us connected to a Solutions Architect.)

### Why are you applying for AWS Activate?
We need cloud credits to validate the Aevus production architecture against early-pilot customer data, with particular interest in Bedrock model invocations (the per-token cost compounds quickly during RCA prompt tuning), SiteWise property-update charges (per-data-point pricing), and managed-service overhead during the first 12 months. As an SDVOSB, we are also pursuing federal contracting opportunities that require evidence of FedRAMP-compatible service usage; Activate credits accelerate that posture without burning runway. Finally, several of our nine products (Signal Storm emergency coordination, Watchman biometric monitoring) share the same AWS architectural baseline — credits applied to one product flow into infrastructure decisions across the portfolio.

---

## 2. AWS Public Sector — SDVOSB pathway

URL: https://aws.amazon.com/government-education/worldwide-public-sector/sdvosb/

### Eligibility
SDVOSB designation confirmed. CAGE Code, DUNS/UEI, SAM.gov registration — fill in from corporate records.

### Primary public sector vertical
Federal — DoD, DOE, DHS. SCADA security and industrial control system observability is in scope for all three. Aevus directly addresses IEC 62443 / NIST 800-82 controls.

### Why AWS public sector?
Three reasons:
1. **Federal posture.** Our SCADA platform targets midstream operators with federal contracting exposure (DOE strategic petroleum reserve, DOD installation utilities). FedRAMP-compatible service usage from day one is non-negotiable.
2. **SDVOSB set-aside opportunities.** AWS Public Sector partnership accelerates our path into SDVOSB SCADA / industrial-IoT set-asides (typically 5% federal contracting goal across agencies).
3. **GovCloud onboarding.** Several anticipated customers will require GovCloud deployment; an early relationship with the AWS Public Sector team de-risks that transition.

### Existing federal opportunities being pursued
(Fill in any specific RFI/RFP names Dave is engaged with. If none yet, list "pre-RFI engagement with DOE midstream and DOD installation utility operators.")

### Solutions Architect engagement requested
Yes — specifically for:
- AWS IoT industrial workloads architecture review
- Bedrock fine-tuning / prompt-engineering best practices for industrial-control narrative generation
- GovCloud onboarding sequence for FedRAMP Moderate posture

### Well-Architected Review credit?
Requested. Aevus's architecture follows AWS's Well-Architected pillars by design (`infra/terraform/` has IaC for the full landing zone, multi-AZ, KMS-managed encryption, CloudTrail with log file validation, S3 Object Lock for compliance). A formal review would harden the patent-positioning evidence.

---

## 3. NVIDIA Inception

URL: https://www.nvidia.com/en-us/startups/

### Company stage
Pre-revenue, building production architecture against physical lab hardware. Code-side feature-complete; deploying to first lab in 2026 Q2.

### AI/ML use cases
- **Real-time inference (Aevus):** Sub-3-second AI root-cause narrative generation on critical SCADA alarms, using Claude via AWS Bedrock today; SageMaker for custom anomaly detection on vibration / RF data once 14 days of training telemetry is collected.
- **Predictive maintenance (Aevus + 3Degz):** AWS Lookout for Equipment for industrial-process anomaly detection. SageMaker for additive-manufacturing print quality prediction (3Degz).
- **Voice / vision (K9 Pet Health):** On-device CV for pet health symptom scanning on iOS. NVIDIA Jetson / Orin Nano modules are likely for the in-clinic stationary version.
- **Spectrum analysis (Aevus RF Analyzer):** GPU-accelerated FFT and anomaly detection on continuous RF data for the spectrum monitoring R&D module under Aevus.

### Compute requirements
- SageMaker training: intermittent, ~1-4 GPU-hours per model build, dozens of builds per quarter during development
- Continuous inference: handled by managed services (Bedrock, L4E) — no own-GPU workload yet
- Edge inference: Raspberry Pi today; NVIDIA Jetson Orin Nano evaluated for higher-fidelity edge use cases (Watchman biometric monitoring, RF Spectrum)

### Existing NVIDIA usage
None yet. Inception credits accelerate the SageMaker training cycle and unlock the Jetson edge path for products where Pi-class hardware tops out.

### Stage of company
Founder-led, SDVOSB, multi-product portfolio. Dave Spencer is the technical founder and operator.

---

## 4. Action checklist for Dave

- [ ] Confirm corporate records (EIN, SAM.gov UEI, CAGE Code) before §2
- [ ] Verify SDVOSB certification status — VetCert or equivalent record
- [ ] Decide on primary AWS account: `676433090238` (existing) or new dedicated `aevus-dev` account before §1
- [ ] Confirm AWS region preference (us-east-2 default per `infra/terraform/variables.tf`) before requesting Solutions Architect engagement
- [ ] Identify the named federal opportunities to list in §2's "Existing federal opportunities being pursued"
- [ ] Submit Activate §1 first (immediate self-serve), then §2 (human-reviewed) and §3 (separate org)

After §1 is approved (24-48h), set Cost Explorer alerts at 25/50/75% of the credit balance before any `terraform apply`. Tag every resource per `docs/AWS_LANDING_ZONE.md` §9.

---

## 5. What we already have ready

- Aevus AWS architecture diagram (`docs/AWS_LANDING_ZONE.md` §2)
- Complete Terraform IaC for the landing zone (`infra/terraform/`)
- 217 tests passing on the code side
- Working synthetic alarm injector + Lambda test harness (no AWS calls needed to demo)
- Operator runbook (`docs/OPERATOR_RUNBOOK.md`) — end-to-end demo script

Anything an AWS Solutions Architect or Inception reviewer asks to see is in the repo. No "we're still figuring it out" required.
