# Radio Comms Page — Design v2 (Task #159)

**Status:** Design intent for the page redesign. Synthesized as a
**role-based checklist** drawing on the Aevus Advisory Board's notional
specialties — per global memory note 2026-05-21, the board is virtual,
so this is **product-simulation brainstorming, not professional
opinion.** Every concrete design choice below is grounded in (a) what
the platform actually collects today and (b) what the audit
(`DATA_COVERAGE_AUDIT_2026-05-30.md`) identified as gaps.

## What's already great about today's page

- Animated SVG RF flow diagram (SCADA host → RAD-01 tower → RF wave
  zone → RAD-02 tower → next-hop). It tells a story.
- Live per-radio callouts: RSSI, Quality, Tx Power, Temp, Volts, IP.
- 24h RSSI sparkline directly under each tower.
- Diagnostic buttons (Run Diag, Packet Stats) with collapsible result
  panel.
- Trend panel with 4 well-chosen series: RSSI, Quality, Packets+Errors,
  Temp+Volts. The chart legends explain WHY each chart matters
  (e.g. "Detect gradual antenna degradation or path obstruction").

We do not regress any of that.

---

## Role-based design checklist

### HMI specialist perspective (ISA-101)

**Operator scanning the page at 6 ft should know in <2 sec:**
- Is the link UP? (binary, top-left, oversized)
- Latency tier (good/warn/bad)
- Uptime % over last 24h
- Any active alarms on either radio
- Any chattering metrics (deadband issue, not real failure)

**Today's gap:** None of these are hero-sized. Operator has to read the
mid-page callouts to assemble the picture.

**Recommendation:** Top KPI strip with 4 large tiles:
- LINK STATE (color-coded, animated when ACTIVE)
- LATENCY (3-tier: green/amber/red, ms with sparkline)
- UPTIME 24H (gauge, % with band coloring at 99/99.9/99.99)
- ALARMS (count, with 1-line summary of most-critical)

### RF engineer perspective

**A real RF eng debugging "the radio sucks today" looks for, in order:**
1. RSSI delta from baseline (not absolute) — is it slowly degrading?
2. SNR / signal quality trend
3. Tx Power — is the radio cranking up to compensate for path loss?
4. Modulation — what's the radio actually using? (degradation reduces
   the modulation order to maintain link).
5. Bit/packet error rate per-direction (Tx errs ≠ Rx errs tells you
   which side has the problem).
6. Temperature trend — thermal drift correlates with RF performance.
7. Voltage — DC supply sag also shifts oscillator stability.

**Today's gap:** TX errors + RX errors + dropped are collapsed into one
"total errors" counter. Modulation is not shown anywhere. RSSI baseline
delta is not surfaced (sparkline shows absolute curve).

**Recommendation:**
- Per-direction error breakdown (TX | RX | DROPPED) as 3 small numbers
  in the per-radio callout
- Modulation field (currently OID `.5727.1.2.2.0` — confirm Trio
  returns it; if not, skip)
- "RSSI vs baseline" mini-indicator: show current dBm AND
  delta-from-24h-mean alongside ("-52 dBm  Δ-3")

### ICS security perspective (IEC 62443)

**A control-system security eng wants to know:**
- Firmware version (CVE matching)
- Last reboot (unauthorized reboot = suspicious)
- Configuration drift (e.g. unexpected SNMP community change after the
  2026-05 JR900 Activate-Config-overwrites-community quirk)
- Unauthenticated traffic (rare on Trio but worth flagging)

**Today's gap:** Firmware version is COLLECTED (we pull MIB OID `.5.0`
into `Asset.firmware` per Task #143) but not shown on the radio page.
Last reboot isn't tracked.

**Recommendation:**
- Firmware field per radio in the security/maintenance callout strip
- "Last config change" timestamp if the radio reports it
- Tooltip on firmware mentioning the version is checked against known
  CVEs (placeholder — actual CVE lookup is a future task)

### SCADA operator perspective (control-room ergonomics)

**An operator on a 12-hour shift wants:**
- Pages that don't require interpretation. If the value is bad, the
  tile should LOOK bad without me reading the number.
- Inline shelve/silence controls. When a metric is chattering, give me
  one click to acknowledge + shelve for 30 min (already implemented
  per Task #122 — surface it here too).
- A "test" button that the operator can use to verify the page is
  alive (vs. stale fetch). Today's "Last Updated: HH:MM" is enough but
  could be more prominent.

**Today's gap:** Shelve UI exists at /api/v1/alerts/{id}/shelve but
isn't reachable from the radio page. The page header doesn't show
freshness clearly.

**Recommendation:**
- Inline ⏸ button next to any chattering meta-alarm — one click =
  POST /api/v1/alerts/{id}/shelve (already auto-shelved by AlertEngine,
  but the operator may want to extend or unshelve).
- Add an "as of HH:MM:SS" stamp under each radio callout that turns
  red when older than 60s (stale-data alarm in-band).

### Patent valuation perspective (P-008 alignment)

**P-008 covers "Edge-Cloud Hybrid Inference Architecture" — sub-second
AI-on-OT-event root cause. The radio page is a strong patent demo
surface because:**
- 1ms RAD ↔ Pi latency is a hero number proving the edge-first claim
- The chattering meta-alarm + RCA narrative integration is unique to
  the Aevus architecture

**Today's gap:** Latency is buried in the SVG path label as a tiny 13px
text. It should be the SECOND-most-prominent thing on the page (after
LINK STATE).

**Recommendation:**
- Make LATENCY a hero KPI tile (top strip)
- When an alarm fires, surface the "RCA narrative ready in <Xs"
  badge — proves the patent claim every time the page is shown
- Latency widget should show p50 / p95 / p99 over last 5 min, not just
  current. p99 is the patent-relevant SLO claim.

---

## Concrete deliverables (this redesign PR)

Ordered by impact-per-effort:

1. **Hero KPI strip** at top of page: LINK STATE | LATENCY | UPTIME 24H
   | ALARMS. Each tile color-coded, oversized fonts. Replaces nothing
   below — purely additive.
2. **Kill the hardcoded `rf-uptime` "100%"** in the SVG — bind to
   actual `UPTIME 24H` vital from the asset feed.
3. **Per-radio callout adds FIRMWARE + ROLE + LINK STATE rows** under
   the existing RSSI/Quality/TxPower/Temp/Volts/IP.
4. **Per-radio chattering badge** — if any vital on this radio is
   currently chattering (per `/api/v1/alerts?asset_id=RAD-01&severity=warning&id_prefix=CHAT-`),
   show a yellow ⚠ chip with the metric name. Click → opens shelve UI.
5. **Fix LINK STATE='ACTIVE' status='bad' bug** in `src/engine/normalizer.py`
   — ACTIVE is the healthy state, should be `good` not `bad`.
6. **Per-direction error split** in callout: replace "ERRORS: N" with
   "TX:N  RX:N  DROP:N" — RF-engineer view.

Deferred to follow-up:
- Modulation scheme (need to confirm Trio reports OID `.5727.1.2.2.0`)
- RSSI baseline delta indicator
- Last-reboot / CVE matching
- p50/p95/p99 latency over 5min (need ms-granularity historian first)

---

## Reversal

Every change is HTML-only or normalizer-only — no schema migrations.
Reverting is `git revert <SHA>`. The audit doc and this design doc
stay regardless.
