# AWS Activate Credits Check — Aevus Pre-Spend Audit

**Status:** Action items for Dave / IL ops
**Last updated:** 2026-05-20
**Why:** Per global Credits First rule, no paid AWS spend before confirming what we already qualify for. Aevus's AWS landing zone (Greengrass + IoT Core + SiteWise + Bedrock + RDS + ECS) will run ~$200/mo at lab scale, scaling to $2K+/mo at first pilot. Activate covers this entirely if we're enrolled at the right tier.

---

## 1. What we need to confirm

| # | Question | Where to check | Why it matters |
|---|---|---|---|
| 1 | Is `676433090238` enrolled in AWS Activate? | Activate portal — https://aws.amazon.com/activate/ → Sign in with root or admin credentials → "My Activate" | Determines all subsequent answers. If not enrolled, we apply today. |
| 2 | Which tier? Founders ($1K), Portfolio ($5K–$100K), or other? | Activate dashboard → "My Benefits" | Founders alone covers ~5 months of lab spend; Portfolio covers a full pilot. |
| 3 | Remaining credit balance and expiration date | Activate dashboard → "Credits" tab; also Billing console → "Credits" | Activate credits typically expire 12–24 months after issue. Worth using them on Aevus buildout vs. letting them lapse. |
| 4 | Are credits applicable to **all** services we plan to use (IoT Core, SiteWise, Bedrock, Greengrass, etc.)? | Activate ToS + each credit certificate fine print | Some credits exclude Marketplace, Reserved Instances, or specific services. Bedrock model invocations sometimes excluded. |
| 5 | SDVOSB-specific benefits? | AWS Public Sector + SDVOSB programs: https://aws.amazon.com/government-education/worldwide-public-sector/sdvosb/ | We may qualify for additional credits, free Well-Architected reviews, and ProServe hours through the SDVOSB pathway. |
| 6 | NVIDIA Inception credit status? | https://www.nvidia.com/en-us/startups/ — check account | Per Credits First rule. Stack with Activate if both apply (NVIDIA covers GPU compute we'd use for SageMaker training). |
| 7 | AWS IoT-specific credits? | Activate dashboard + AWS IoT team contact | AWS sometimes offers targeted IoT credits for industrial-IoT startups — worth asking the Activate rep directly. |
| 8 | Free-tier eligibility on `676433090238`? | Billing console → "Free Tier" | Account creation date determines 12-month free tier window. If still inside it, IoT Core / Lambda / S3 free-tier covers most of the lab spend on top of Activate. |

---

## 2. Outreach plan

If we are **not currently enrolled**:

1. Apply via https://aws.amazon.com/activate/ today. Founders tier ($1K) is self-serve and approved in 24–48 hours.
2. Cite SDVOSB status in the application — may route us into Portfolio tier automatically.
3. Apply separately to **AWS Public Sector Partner Program** (SDVOSB pathway) for the larger benefit package.

If we are **enrolled but at a lower tier**:

1. Open a case via the Activate console asking to be upgraded based on:
   - SDVOSB designation
   - 9 products in development under one entity
   - Federal contracting pursuit (mention specific upcoming opportunities if any are nameable)
2. Ask the assigned Activate rep about IoT-vertical and industrial-vertical credit programs.

If credits are **fully sufficient** for the next ~12 months:

1. Proceed with AWS landing zone build per `AWS_LANDING_ZONE.md` §11 action items.
2. Tag every Aevus resource with `product=aevus, env={dev|prod}, cost-center=aevus` so we can track burn against the credit pool.
3. Set a **Billing Alarm** at 25 / 50 / 75% of remaining credit balance.

If credits are **insufficient**:

1. Defer non-essential cloud components (RDS Aurora can wait — use SQLite on the edge longer; CloudFront-fronted dashboard can defer behind a free-tier CloudFront).
2. Prioritize SDVOSB Public Sector application before any large spend.
3. Revisit budget approval with the board.

---

## 3. Tagging convention for credit tracking

Every Aevus AWS resource must be tagged at creation:

```
product       = aevus
env           = dev | prod | shared
cost-center   = aevus
component     = collector | api | dashboard | storage | ai | audit | network
managed-by    = terraform | greengrass | manual
```

Cost Explorer + Budgets can then break burn down per component and flag the worst offenders before they drain credits.

---

## 4. Specific things to ask the Activate rep

If we get a human conversation with an Activate rep, bring this list:

1. "We're SDVOSB. Does that change our Activate tier eligibility?"
2. "We have nine products in development. Is there an IL-wide enrollment vs. per-product?" (Answer is usually per-account, but worth confirming.)
3. "Are IoT Core message charges, SiteWise property charges, and Bedrock model invocation charges all credit-eligible?"
4. "What's the path from Activate to Well-Architected Review credits?"
5. "Can we get connected to an AWS Solutions Architect specializing in industrial IoT for the landing-zone design?" (Often free with Activate, valuable for the Aevus reference architecture.)
6. "Is there an IoT industrial vertical credit program currently active?"
7. "We're targeting federal contracting (SDVOSB). What's the GovCloud onboarding path and credit applicability?"

---

## 5. Decision gates

**Gate 1 — before any AWS resource creation:**
- Activate enrollment confirmed
- Credit balance sufficient for 6 months of projected lab spend ($1.2K min)
- Billing alarms set

**Gate 2 — before first pilot customer onboarding:**
- Multi-account migration plan approved
- Production budget approved by board
- SDVOSB Public Sector enrollment complete (if federal in scope)

**Gate 3 — before federal pursuit:**
- GovCloud account stood up
- FedRAMP service inventory confirmed
- Customer-managed KMS keys in place

---

## 6. Action owner

Dave to drive — most of this is portal access that needs root or admin credentials. Claude can prep Terraform / IAM templates once tier and budget are confirmed.

**Target completion:** before any work starts on `AWS_LANDING_ZONE.md` §11 action items.
