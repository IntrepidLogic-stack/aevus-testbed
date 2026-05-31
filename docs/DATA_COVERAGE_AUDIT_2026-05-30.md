# Aevus Dashboard — Live Data Coverage Audit

**Date:** 2026-05-30
**Scope:** `dashboard/Aevus_Console.html` (7,086 lines) vs. live telemetry from the 7 production assets (EDGE-01, EFM-01, RAD-01, RAD-02, RTR-01, RTU-01, SW-01)
**Method:** Static read of page-section markup + JS render hooks. "Currently displays" = element IDs/slots present in the active HTML. "Available but not displayed" = vitals from the production fleet that have no matching hook on that page.

> **Architecture note.** Most operational pages (`historian`, `network`, `cyber`, `reports`, `solar`, `cabinet`, plus `assets-table-wrap`, `health-bars-wrap`, `ops-correlations-detail`) are empty placeholder divs that get filled by JS renderers from the asset/vitals feed. Their data coverage is bounded by what those renderers ask for, not by HTML markup. The audit calls out gaps based on the live vital labels the renderers iterate over.

---

## OVERVIEW (`data-page="overview"`)

**Currently displayed (lines 4298–4375):**
- Situation banner, alarm summary strip
- Dense KPI bar: production hero, fleet health bar, health score, mini-KPIs
- `#process-schematic` (live digital twin P&ID hero)
- AI prediction hero + active alerts list
- Activity feed / Comm Status tabs
- IL9000 predictions list
- Legacy hidden tiles: `#kpi-assets`, `#kpi-health`, `#kpi-predictions`, `#kpi-alerts`

**Available from live fleet but not surfaced:**
- **EDGE-01 collector health** — CPU TEMP, MEM USED PCT, FAILED SERVICES, UPTIME 24H. If the edge dies, every other tile is stale; today there's no "collector heartbeat" pill on overview.
- **Per-asset comm latency** (RTU-01 polled at 5s, radios at 30s, RTR-01/SW-01 SNMP) — fleet health bar collapses this into one number.
- **Chattering / shelved alarm counts** — ISA-18.2 meta-alarms exist in AlertEngine (Tasks #121/#122) but the KPI strip doesn't break them out.
- **EFM-01 flow + accumulated volume** — this is the only "production" number we actually have telemetry for, and it doesn't drive `#ov-production-hero`.

**Recommend:**
1. Wire `#ov-production-hero` to EFM-01 FLOW RATE + ACCUMULATED VOLUME (replace BOPD placeholder with real MCFD).
2. Add an EDGE-01 collector-health pill to the KPI bar (CPU TEMP / FAILED SERVICES / 24H UPTIME).
3. Split `#kpi-alerts` to show critical / warning / **chattering** / **shelved** — meta-alarm visibility is a key Patent P-008 differentiator and it's invisible today.

---

## ASSETS (`data-page="assets"`)

**Currently displayed (line 4378):** `#asset-filters` + `#assets-table-wrap` — table built in JS from the asset feed.

**Available but commonly missing from table columns:**
- **Firmware version** (Task #143 populates this for Trio; SCADAPack/MikroTik/Cisco also have it). Column not visible.
- **Last-seen age in seconds**, not just status pill — operators need to spot stale rows fast.
- **Polling protocol** (SNMP v2c / Modbus TCP / DNP3 / ICMP / self-metrics) — answers "why is this asset weird?" in one glance.
- **Chattering flag** per asset (already computed in AlertEngine).

**Recommend:**
1. Add Firmware + Protocol + Last-Seen-Δ columns; sortable.
2. Surface chattering-asset badge in the row's status pill (ISA-18.2 §7).
3. Quick-filter chip for "stale > 2× poll interval."

---

## ALARMS (`data-page="alarms"`)

**Currently displayed (4393–4409):** Active / History / Shelved / Analytics tabs; filter bar; `#alarm-rationalization` panel.

**Available but not displayed:**
- **Chattering meta-alarm cluster view** — backend identifies chattering, but UI just shows individual occurrences.
- **Per-asset alarm rate** (alarms/hr per asset) — ISA-18.2 §16 KPI.
- **Top-10 nuisance alarms** by frequency — drives rationalization decisions.
- **First-out / sequence-of-events** when multiple alarms fire in <1s (RTU-01 has 41 process vitals; cascade is real).

**Recommend:**
1. Add a "Chattering" tab next to Shelved that groups occurrences by source signal with a flap-count + last-N-minutes sparkline.
2. In Analytics tab, show alarms/hr per asset bar chart + ISA-18.2 compliance scorecard (target ≤6/hr/operator).
3. First-out badge on the leading alarm in any <1s cluster.

---

## HEALTH (`data-page="health"`)

**Currently displayed (4385–4390):** `#health-stats` summary + `#health-bars-wrap` per-asset bars.

**Available but not displayed:**
- **Driver attribution** — Health score formula weights comm-reliability 35% / vitals 30% / risk 20% / maintenance 15%. UI shows the composite, not what dragged it down.
- **Per-class score** (radio vs. RTU vs. network vs. edge) — exposed by `/api/v1/health/summary` per CLAUDE.md.
- **Trend arrow** vs. 24h ago — health bar is a point-in-time read.
- **Maintenance-currency factor** for RTU-01 (RUN HOURS / maintenance-due — Task #124).

**Recommend:**
1. Click-to-expand each health bar into a stacked "why" view (the 4 weight components).
2. Add per-class health tiles at top of page (Radio / RTU / Network / Edge).
3. 24h delta arrow on each bar.

---

## HISTORIAN (`data-page="historian"`)

**Currently displayed (4833–4835):** Single empty `#historian-page` div, JS-rendered.

**Available but uncertain coverage:**
- All 348 vitals across the 7 assets are written to InfluxDB. Historian should browse every one of them — confirm renderer enumerates the full vital set, not just a curated list.
- **Annotation overlay** — alarm fire/clear events on the trend line. Backend has the events.
- **Multi-pen compare** across assets (e.g. RAD-01 RSSI vs. RAD-02 RSSI on one chart).

**Recommend:**
1. Verify historian metric picker is auto-populated from `/api/v1/diagnostics/signals` or equivalent — not a hardcoded list. If hardcoded, switch to dynamic.
2. Overlay alarm events as vertical markers on the chart.
3. Add 2-pen and 4-pen compare modes; persist in URL params.

---

## NETWORK (`data-page="network"`)

**Currently displayed (4837–4839):** Empty `#network-page` div.

**Available but underused (SW-01 alone has 172 vitals, RTR-01 has 77):**
- **Per-port octets in/out** for SW-01 FastEthernet0/1–24 and RTR-01 bridge ports — heatmap or top-talker bar is much more useful than 200 raw counters.
- **Per-port error / discard rate** — set ISA threshold (>100/min warn, >1000/min critical) and highlight.
- **CDP neighbor count** on SW-01 and RTR-01 — topology truth check (Task #95 ran into this).
- **CPU LOAD + BOARD TEMP + BOARD VOLTAGE** for RTR-01 (already polled).
- **Link state map** — which ports are up/down/disabled.

**Recommend:**
1. Per-switch port matrix: 24 cells, color by oper status, hover = bps in/out + errors.
2. Top-N talkers chart (highest octet delta over last poll window).
3. Surface CDP neighbor table — proves the network diagram matches reality.

---

## RADIO (`data-page="radio"`) — DEEP DIVE

**Currently displayed (4522–4832):**
- RF status bar: `#rf-link-status`, `#rf-link-meta`
- Animated RF flow SVG (SCADA Host → RAD-01 → 900 MHz waves → RAD-02 → Field Device EFM-01)
- Per-radio callout cards: RSSI, QUALITY, TX PWR, plus TEMP / VOLTS / IP secondary row
- 24h RSSI sparkline + trend dot per radio
- Center metrics strip: PACKETS, ERRORS, **LATENCY**, **UPTIME** (slots exist — confirm wired)
- Link quality bar w/ EXCELLENT label
- Bottom KPI strip `#rf-kpi-strip`
- 4 trend cards (toggleable): RSSI, Quality, Packet Loss, Temp+Voltage

**Confirmed MISSING / not visibly surfaced** (you flagged these — all confirmed):
- **LATENCY** — slot `#rf-latency` exists in SVG (line 4668) but the labeled "LATENCY" header is there with no big-format hero treatment. The 1 ms reality is patent-grade evidence and should be a prominent KPI tile in `#rf-kpi-strip`, not a 13px number on the path.
- **UPTIME 24H** — `#rf-uptime` is hardcoded `100%` in the SVG (line 4669). Task #145 computed real 24h reachability — verify the renderer overwrites this static value; if not, the dashboard is lying.
- **Firmware (3.8.4 Build 4104)** — no slot anywhere on the page. Task #143 fetches it; should appear in each radio callout below IP.
- **ROLE (MASTER vs. REMOTE)** — `#rf-band-mode` shows generic "AP ↔ Remote." RAD-01 is hardcoded "Access Point" (line 4591); RAD-02 hardcoded "Remote" (line 4687). Should be driven by the live ROLE vital, not the SVG text.
- **Chattering meta-alarm** — no badge or halo on either tower when a signal is chattering. The `#rf-r1-alarm-halo` / `#rf-r2-alarm-halo` circles exist (lines 4576, 4675) — they're a perfect home for chattering state, currently used only for hard-alarm.

**Additionally missing from the 14 radio vitals:**
- **SIGNAL QUALITY** — `#rf-r1-qual` / `#rf-r2-qual` ARE present, but the underlying SNR (`5727.1.1.2.0`) is distinct from a quality % and isn't visibly labeled.
- **TX/RX/DROPPED ERRORS broken out** — the path shows one `#rf-total-err` combined number; the trend card has the legend (Errors / Dropped / Retransmits) but the hero strip collapses three counters into one.
- **TX/RX PACKETS counter delta** (not totals) — totals roll up to "263 million packets" which is useless; delta over last poll is the operational read.
- **LINK STATE** as a discrete vital (in addition to RSSI inference) — should drive the `#rf-link-status` indicator color directly.
- **Modulation scheme** (OID `.5727.1.2.2.0` per CLAUDE.md) — predictive: if modulation steps down from QPSK to BPSK, that's a degradation signal before RSSI tanks.

**Recommend (top 3):**
1. **Promote LATENCY + UPTIME-24H to top-of-page KPI tiles** with big numerals — these are the patent-worthy data points (1 ms, 100%) and should anchor the demo, not hide on the SVG path. Replace the hardcoded `100%` and `—` defaults with live-bound text overwritten on every render.
2. **Add a 3rd line to each callout: FW + ROLE + LINK-STATE.** Use the alarm-halo circle for chattering meta-alarm state (amber halo) distinct from hard alarms (red halo).
3. **Modulation widget** in the center column ("QPSK ↔ BPSK" with last-change timestamp) — earliest leading indicator of RF degradation; differentiates Aevus from any generic SNMP poller.

---

## OPERATIONS (`data-page="operations"`)

**Currently displayed (4845–4859):** Safety banner (hardcoded "0 incidents"), weather detail, `#ops-command-panel`, `#ops-command-log`, `#ops-correlations-detail`.

**Available but not displayed:**
- **RTU-01 commands queued / executed / blocked-by-IL9000** — IL-9000 interlock is the central patent claim; it should be visibly counted here.
- **EFM-01 BTU / CO2 / ENERGY RATE** — gas-quality is the operations-team metric; not visible anywhere.
- **Cross-domain correlation hits** — `#ops-correlations-detail` is a placeholder; show actual signal pairs that co-fired (RAD-01 RSSI ↓ AND RTU-01 COMPRESSOR LOADED ↓ within 60s).

**Recommend:**
1. Add an IL-9000 interlock counter ("N firmware-write attempts blocked, M scheduled for site tech") — patent-evidence widget.
2. Gas-quality strip showing EFM-01 BTU CONTENT, CO2 CONTENT, ENERGY RATE.
3. Wire correlation panel to actual co-occurrence detector output.

---

## SOLAR (`data-page="solar"`) + CABINET (`data-page="cabinet"`)

**Currently displayed:** Empty `#solar-content` and `#cabinet-content` divs.

**Available but not displayed:**
- **RTU-01 SOLAR VOLTAGE + BATTERY + CHARGE CURRENT** (CLAUDE.md Modbus register 40013, plus battery/charge — in the 41 RTU vitals).
- **EFM-01 BATTERY** (1 of its 17 vitals).
- **RTR-01 BOARD VOLTAGE** — supply-rail proxy.
- **EDGE-01 power** — Pi has no native voltage sensor, but uptime + thermal can stand in.

**Recommend:**
1. Solar page should be RTU-01 + EFM-01 power-system mini-dashboard: solar V, battery V, charge current, derived state-of-charge estimate, 24h discharge curve.
2. Cabinet page should be the wiring-diagram view (network-diagram.svg already in /docs) overlaid with live link state per port — convert that SVG to a live element.

---

## WEATHER (`data-page="weather"`)

**Currently displayed (4431–4512):** Rich SCADA-grade weather grid — current conditions, ops impact panel, 7-day forecast, wind/precip 48h, 24h hourly strip.

**Note:** This page is fed by an external weather API, not the 7-asset fleet. Coverage gap here would be **operational-impact linkage** — i.e. wind speed crossing 40 mph should auto-suggest "schedule RTU-01 maintenance window now" or "expect RF degradation on RAD-02 (downwind antenna)."

**Recommend:**
1. Cross-link wind/temp thresholds to predicted asset risk — show "RAD-02 antenna sway forecast: 6° at 18:00" or "EFM-01 cold-snap battery derate likely 04:00."
2. Surface ambient delta vs. RTU-01 AMBIENT TEMP (sanity-check the in-cabinet vs. outdoor reading).

---

## TRENDS (`data-page="trends"`)

**Currently displayed (4861–4883):** Search bar, metric filter bar `#trend-metric-bar`, `#trend-chart-wrap`, click-detail overlay.

**Available but uncertain:**
- Same as Historian — does the metric list enumerate all 348 fleet vitals or just a curated subset? RTR-01's 77 metrics and SW-01's 172 are easy to under-represent.
- **Saved views** — operators want a "my pump dashboard" view; no persistence visible.
- **Multi-asset overlay** (same as historian).

**Recommend:**
1. Auto-populate metric picker from live vital labels — group by asset class. Make it obvious RTR-01 has 77 trends and SW-01 has 172.
2. URL-shareable trend views (?metrics=RAD-01.rssi,RAD-02.rssi&range=24h).
3. Promote the existing `#trend-search` typeahead — works for "pressure" but operators don't know to type it.

---

## MAP (`data-page="map"`)

**Currently displayed (4516–4520):** Single full-viewport `#aevus-map` div.

**Available but not displayed:**
- **Live per-site asset status pins** — Killdeer Field has 7 assets, the map should cluster + color-code them.
- **RF link line between RAD-01 and RAD-02** with live link quality color.
- **Weather radar overlay** (data is already in the weather page).

**Recommend:**
1. Drop live status pins for the 7 assets at Killdeer Field coords.
2. Draw the radio link as a colored line (green/amber/red by 5-min RSSI rollup).
3. Wire site-card click → map zoom-to-site.

---

## SITES (`data-page="sites"`)

**Currently displayed (4934+):** Killdeer Field card (HARDCODED: assets=7, health=89, alerts=50) + 3 "coming soon" cards (Permian, Eagle Ford, DJ Basin).

**Problem:** The Killdeer numbers are static. With 7 live assets feeding the dashboard, the site card should be the most-correct number on the page and it's not.

**Recommend:**
1. Bind Killdeer assets/health/alerts to live aggregates (asset count from `/api/v1/assets`, health from `/api/v1/health/summary`, alerts from `/api/v1/alerts?status=open`).
2. Show a tiny per-asset-class breakdown chip (1 edge, 1 EFM, 2 radio, 1 router, 1 RTU, 1 switch).

---

## Cross-cutting "ship next" priorities

If we can only ship 5 things this week, in order:

1. **Radio page: promote LATENCY + UPTIME-24H to KPI tiles + add FW/ROLE/LINK-STATE to each callout** — patent-evidence visibility, 1-day fix.
2. **Kill the hardcoded Killdeer Field numbers on Sites page + the hardcoded `100%` UPTIME on Radio** — these are actively misleading.
3. **Network page: per-port matrix for SW-01 + top-talkers chart** — 172 vitals are currently invisible.
4. **Alarms: Chattering tab + per-asset alarm-rate chart** — ISA-18.2 §7/§16 KPIs, code already exists.
5. **Overview: EDGE-01 collector-health pill + real EFM-01 flow in the production hero** — the dashboard's most-watched widgets should reflect live data, not placeholders.

## Known data-source caveats

- **RTU-01 is simulated** (Task #134 — SCADAPack still at 172.16.1.200, polling not wired). The 41 process vitals listed are from the simulator, not real lab hardware. Anything we ship for RTU-01 should be labeled SIMULATED in the UI until #134 lands.
- **SW-01 Cisco Catalyst** SNMP went live in Task #92; CDP/port-speed had a silent-fail issue (#95, fixed in #100).
- **RAD-02** was bench-restored in Task #139; verify both radios are still online before screenshotting.
