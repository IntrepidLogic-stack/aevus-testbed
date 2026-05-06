# BRAND SYSTEM — Aevus

**Authority:** This document is the locked specification. Any asset produced in this project must conform to it. If a prior asset conflicts, the prior asset is wrong, not this document.
**Owner:** Woody, Founder, Intrepid Logic LLC (SDVOSB)
**Version:** 2.0 (May 2026 brand evolution)
**Supersedes:** v1.0 ("Aevus by SCADAX" green-accent system)

---

## 0. What Changed in v2.0

| Element | v1 (retired) | v2 (canonical) |
|---|---|---|
| Brand name | Aevus by SCADAX — Powered by Intrepid Logic | **Aevus** |
| Tagline | (none) | **PREDICT. PREVENT. PERFORM.** |
| Primary accent | Green `#00FF88` → `#00CC6A` | Electric teal `#06B6D4` → `#0EA5E9` |
| Status palette | Green-dominant, monochromatic | Multi-color: teal/green/amber/red/purple/blue as semantic categories |
| Logo mark | Generic green disc with "A" | **Geometric "A" with diagonal cut-outs** in teal |
| App layout | Top-tab navigation | **Persistent left sidebar** |
| Intrepid Logic visibility | "Powered by Intrepid Logic" prominent | Footer copyright only ("© Intrepid Logic. All rights reserved.") |

The v1 collateral suite (2-pager, case study, PPTX decks) was built to v1 brand and will need re-rendering against v2 before further external use.

---

## 1. Naming Hierarchy

| Element | Form | Use |
|---|---|---|
| Product name | **Aevus** | All headlines, body copy, in-product UI, marketing. |
| Tagline | **PREDICT. PREVENT. PERFORM.** | Pairs with logo on title surfaces; small caps, letter-spaced. Never extends or rewords. |
| Company | **Intrepid Logic LLC** | Legal, contracts, signature blocks, copyright lines. |
| Company short | **Intrepid Logic** | Footer attribution only. |
| Certification | **SDVOSB** (Service-Disabled Veteran-Owned Small Business) | Always spelled out at first use; abbreviation thereafter. Appears in footer of all collateral. |

**Never use:** "Aevus by SCADAX," "SCADAX," "Powered by Intrepid Logic," or any v1 naming. These are retired.

---

## 2. Visual Identity

### 2.1 Color System (v2)

#### Brand & Accent

| Token | Hex | Use |
|---|---|---|
| `--accent` | `#06B6D4` | Logo, primary brand accent, active nav state, CTA fills, primary chart series. |
| `--accent-bright` | `#22D3EE` | Hover states, focused inputs, link color, glow accents. |
| `--accent-dim` | `#0E7490` | Pressed states, secondary accent surfaces. |
| `--accent-glow` | `rgba(6,182,212,0.18)` | Outer-glow ring on KPI icon backgrounds. |

#### Backgrounds

| Token | Hex | Use |
|---|---|---|
| `--bg-app` | `#0B1020` | Sidebar background — deepest layer. |
| `--bg-canvas` | `#0F1629` | Main content canvas — middle layer. |
| `--bg-card` | `#161E33` | Card / panel base. |
| `--bg-elevated` | `#1E2742` | Elevated card, hovered row, popover. |
| `--bg-input` | `#1A2238` | Form inputs, dropdowns. |

#### Text

| Token | Hex | Use |
|---|---|---|
| `--text-primary` | `#FFFFFF` | Headlines, KPI values. |
| `--text-secondary` | `#B4BCD0` | Body copy, secondary labels. |
| `--text-muted` | `#7B8499` | Captions, helper text, table column labels. |
| `--text-faint` | `#4A5168` | Disabled state, version labels. |

#### Status (semantic)

| Token | Hex | Meaning |
|---|---|---|
| `--status-good` | `#10D478` | Healthy, online, success. |
| `--status-warn` | `#FBBF24` | Warning, performance degradation, calibration overdue. |
| `--status-bad` | `#EF4444` | Critical, offline, failure. |
| `--status-info` | `#60A5FA` | Informational alerts, firmware available. |
| `--status-unknown` | `#A78BFA` | Unknown / unclassified state, also used for "predicted failures" KPI hue. |
| `--status-offline` | `#6B7280` | Offline / no signal. |

### 2.2 Typography

| Use | Family | Weights |
|---|---|---|
| Display + body | **Manrope** | 400, 500, 600, 700 |
| Mono / numeric | **JetBrains Mono** | 400, 500, 600 |
| Office documents | Calibri + Consolas | (preserved for docx/pptx fallback) |

### 2.3 Logo

Geometric "A" formed by two diagonal bars with negative-space cut-outs. Rendered in `--accent` (teal). Wordmark "Aevus" sits to the right in Manrope 700. Tagline "PREDICT. PREVENT. PERFORM." sits below the wordmark in 9–10pt mono, letter-spaced, in `--text-muted`. Reproduced at the top of the sidebar (full lock-up) and as a watermark in the lower-right of full-app footers.

### 2.4 Layout

- **Sidebar:** 240px fixed, `--bg-app`, persistent. Logo lock-up at top. Nav items below. Account widget + version label at bottom.
- **Main canvas:** flex-1, `--bg-canvas`, padded 24px.
- **Top bar within main:** flex row, page title block on left, contextual chips and status indicators on right.
- **Cards:** `--bg-card`, 1px subtle border, 12px radius, 16–20px internal padding.

---

## 3. Locked Figures (Pilot Modeling — Unchanged from v1)

### 3.1 Operational
- Message delivery: 77% → 96.3% (modeled improvement)
- Monthly outages: 18 → 3
- MTTR: 4.2h → 0.8h
- Annual loss before: $2.3M
- Modeled annual savings: $1.1M
- Year-1 platform investment: $325K
- Payback: 4.2 months
- Seed target: $1.5–$2M at $6–$8M pre-money

### 3.2 Gas Measurement (industrial rate)
- Henry Hub reference: $3.50/MMBtu · Industrial rate: $4.21/MCF
- Per-meter monthly loss: $22,256 · annual: $267,072
- Total fleet exposure: $7.21M across 27 meters
- Fleet compliance score: 98.2% (AGA-3 99.4%, API 21.1 97.8%, Audit 96.1%, Calibration 88.5%)

### 3.3 IP Portfolio
- 7 patentable inventions (P-001 to P-007; P-008 = IL-009 firmware safety interlock)
- 5 registrable trademarks (Aevus, Intrepid Logic, AI SCADA Engineer, PREDICT. PREVENT. PERFORM., plus one TBD; SCADAX-era marks deprecated with v2 brand)
- 7 copyrightable works
- Manufacturer licensing potential: $3.5M–$11.5M/yr aggregate

### 3.4 Roadmap
- Phase 01 Foundation (Y1) · Phase 02 Predictive Scale (Y2) · Phase 03 5G Migration (Y3) · Phase 04 Autonomous Ops (Y4-5)

---

## 4. Hard Rules

1. **IL-009 Firmware Safety Interlock** — PLC firmware updates are never automated remotely. Patentable distinction (P-008) and must appear in any technical or sales material that touches firmware orchestration.
2. **Pre-revenue honesty** — Intrepid Logic is pre-revenue with no signed pilot customers. All case studies and operational impact figures must be labeled as **modeled**.
3. **SDVOSB attribution** — Every external artifact carries the SDVOSB designation in the footer.
4. **Buyer priority lens** — All messaging frames in terms of ROI / RISK / OPS (Greg's framework).
5. **Tagline integrity** — "PREDICT. PREVENT. PERFORM." is reproduced verbatim.

---

## 5. v1 Asset Reconciliation

These v1 artifacts in /mnt/user-data/outputs use retired branding and need v2 re-renders before further external use:

- `Aevus_by_SCADAX_2Pager.docx` / `.pdf` / `.pptx`
- `Aevus_by_SCADAX_CaseStudy.docx` / `.pdf` / `.pptx`
- `Aevus_by_SCADAX_Console.html` — superseded by v2 console

The data inside (locked figures, roadmap, IP claims) remains valid; only the visual / naming / typographic skin needs updating.
