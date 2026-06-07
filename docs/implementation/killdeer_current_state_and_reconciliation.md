# Killdeer Field / BlueJay #1 — Current State & Program-Control Reconciliation

**Date:** 2026-06-07
**Type:** Program-control checkpoint (read-only — no code, no UI, no deploy)
**Purpose:** Stop the cycle, reconcile what's on disk against the plan, and decide what (if anything) is the next safe step before more Killdeer code is written.
**Companion artifact:** [docs/implementation/killdeer_reconciliation_audit.md](docs/implementation/killdeer_reconciliation_audit.md) — deeper file-level audit; cited but not repeated here.

---

## 1. Current State

### 1a. Active repositories

| Repo | Path | Role | Killdeer surface |
|---|---|---|---|
| Aevus platform (testbed) | [AEVUS_filesv2/testbed-kit/](AEVUS_filesv2/testbed-kit/) | FastAPI backend + dashboard. Owns `twin.py`, asset registry, alarms, 3D twin, Spline harness. | All of it. |
| Drawings | [drawings/](drawings/) | Rev A drawing package (HTML + PDF + handoff zip). | The reconciled artifact. |
| Marketing / website | [aevus_io/](aevus_io/) | Vite + React marketing site. | None — no Killdeer references in `src/` or `public/`. |

The "platform" in everything below means **AEVUS_filesv2/testbed-kit/** unless stated. The marketing site is out of scope for this checkpoint.

### 1b. Branches / commits / tags

**testbed-kit (Aevus platform):**
- `origin/main` HEAD: `8a501eb` — merge of PR #103 "feat(process-assets): add flagged CMP asset binding path" (`b7f83b6` ← `6682741`).
- Local working branch: `feat/process-assets-cmp-binding-flagged` (still checked out at `6682741`). Tree clean.
- 47 local branches; only `main` + four small recent fix branches are pushed.
- The PR #103 merge introduced:
  - `src/api/process_assets.py` (new, +97) — dormant overlay
  - `src/config.py` — `process_assets_enabled: bool = False`
  - `src/api/assets.py` (+17) — overlay append, no-op when flag off
  - `src/api/twin.py` (+14) — explicit `_DEMO_FACILITIES` allowlist; `/process` now 404s outside the demo facility
  - `tests/test_process_assets.py` (+95), `tests/test_twin.py` (+12)

**drawings:**
- `main` HEAD: `0d1e292` — release commit "release(killdeer): add Rev A drawing exports and handoff bundle".
- Prior commit: `4a2ba65` — source commit "docs(killdeer): add complete drawing register and modeled reference package".
- Tag: `rev-A` (on `0d1e292`).
- Tree clean, no untracked files.
- Bundle on disk: `Killdeer_Field_Digital_Twin_Handoff_Rev_A.zip` (2.7 MB), plus the HTML sheets and PDF exports.

**aevus_io (marketing):**
- `main` HEAD: `72249bd` (Datadog RUM swap). Tree clean. Not Killdeer-related.

### 1c. What is deployed

- testbed-kit `main` at `8a501eb` was promoted to production **flag-off** (`PROCESS_ASSETS_ENABLED=` unset → default `False`). Smoke tests passed.
- `/api/v1/assets` is byte-identical to pre-merge while the flag is off (commit message guarantee; CI green; verified by `tests/test_process_assets.py`).
- `/api/v1/twin/facility/{id}/process` now returns 404 outside the `_DEMO_FACILITIES` allowlist — this **is** a live behavioral change, but it tightens the demo gate rather than expanding surface area.

### 1d. What is dormant behind flags

- `PROCESS_ASSETS_ENABLED` (config: `settings.process_assets_enabled`, env: `PROCESS_ASSETS_ENABLED`, default `False`). When flipped:
  - A derived CMP (Field Sales Compressor) asset is appended to `/api/v1/assets` and resolves on `/api/v1/assets/CMP`.
  - Vitals are built from already-polling SCADAPack-470 (RTU-01) compressor-group registers — no new collectors, no new ingest path.
  - Worst-of vital status drives the CMP asset status; health is a coarse `{bad:35, warn:70, good:96}` map.
- `REFERENCE_ASSETS_ENABLED` (pre-existing) remains on its prior posture (`prod=1, default 0` per `docs/env`). Out of scope here.

### 1e. What is local-only and not pushed

- testbed-kit: 40+ feature/fix branches exist locally that are not on `origin`. None are Killdeer-shaped beyond the merged PR #103. Drawing reconciliation produced **only** documentation — no code commits — so there is no Killdeer working tree to push.
- aevus_io: ~30 unpushed feature branches; none touch Killdeer.
- drawings: nothing local-only.

### 1f. Source-of-truth verification (snapshot today)

- `grep -c "TwinNode("/_"TwinEdge("` on `AEVUS_filesv2/testbed-kit/src/api/twin.py` → **26 / 27** (raw grep counts including the `class TwinNode(...)`/parent-class lines).
- `tests/test_twin.py` pins `len(nodes) == 25` / `len(edges) == 26` and is green — i.e. the live `_TOPOLOGY` list is **25 nodes / 26 edges** (the extra grep matches are the class definitions and a non-list reference). This matches the user-stated contract.
- `drawings/VALIDATION_SUMMARY.txt` reports `26 nodes / 27 edges` — stale by one in each direction (drift between drawing-validation moment and the current twin). Not a code issue.

---

## 2. Original Intended Sequence

| # | Stage | Output | Gate before next stage |
|---|---|---|---|
| 1 | Engineering Basis Package | Field description, P&ID intent, asset list, telemetry/alarm/health model intent | Basis accepted as the contract |
| 2 | Drawing Package (Rev A) | PFD, P&ID, Plot, Iso, Drawing Register — validated against `twin.py` | Drawings released under a Rev tag |
| 3 | Claude Code Handoff Package | Implementer-facing brief that maps drawings + basis onto code surfaces | Handoff readable end-to-end without spelunking |
| 4 | Reconciliation Audit | File-level diff: what's in code vs. what's in drawings/basis; classify every delta | Findings classified; smallest-safe-ticket identified |
| 5 | Smallest Safe Implementation Ticket | One PR, behavioral no-op or flag-gated, no schema/API contract change | PR merged flag-off, CI green |
| 6 | Controlled Validation | Flag flipped in a non-prod surface; observe `/assets`, `/twin/.../process`, dashboard; revert plan rehearsed | Telemetry and alarm behavior verified at parity |
| 7 | Production Enablement | Flag flipped in prod with a documented rollback (unset env var) | Operator sees CMP as a first-class asset |

---

## 3. Actual Sequence So Far

In the order things landed on disk / in git:

1. Engineering Basis Package authored. ✅ (matches plan step 1)
2. Drawing Package Rev A authored, validated against `twin.py`, released and tagged. ✅ (matches plan step 2; the Rev A `VALIDATION_SUMMARY.txt` was generated against a slightly-newer `twin.py` snapshot — see V-1 below.)
3. Handoff Package (Claude Code) authored. ✅ (matches plan step 3)
4. **First drift point.** Before a written reconciliation audit, the implementer authored and merged PR #103 (`feat(process-assets): add flagged CMP asset binding path`) — the smallest-safe-ticket — and promoted to production flag-off. CMP overlay + `/process` demo-gate landed live (flag-off).
5. Reconciliation audit written **after** the code change shipped: [docs/implementation/killdeer_reconciliation_audit.md](docs/implementation/killdeer_reconciliation_audit.md) (2026-06-06).
6. **Current checkpoint.** This document — program-control rewind to reconcile plan vs. reality before any more code is written.

**Where the order drifted:** steps 4 and 5 swapped. The audit that was supposed to *select* the smallest safe ticket was written *after* a ticket had already been chosen, implemented, merged, and deployed (flag-off). The deploy itself is defensible (flag-off, behavioral no-op on `/assets`, only side-effect is the `/process` demo-gate tightening — arguably a hardening, not an expansion). But the audit step did not perform its gating function in the intended order, and no controlled-validation step (plan step 6) was run before the production deploy because nothing flag-on shipped.

There is **no controlled-validation evidence** for the flag-on path yet. There is **no `PROCESS_ASSETS_ENABLED=1` posture** in any environment yet.

---

## 4. Gap Analysis

Per the user's classification: COMPLETE / PARTIAL / MISSING / RISK / DEFER.

### Engineering basis, drawings, handoff
| Item | Class | Note |
|---|---|---|
| Engineering Basis Package | **COMPLETE** | Authored; accepted as the contract that PFD/P&ID/Iso were validated against. |
| Drawing Package Rev A — source files | **COMPLETE** | 5 HTML sheets + 6 PDFs + register; tag `rev-A` on `0d1e292`. |
| Drawing Package Rev A — validation against `twin.py` | **PARTIAL** | `VALIDATION_SUMMARY.txt` says 26/27; live `_TOPOLOGY` is 25/26. Drift of one in each direction. (V-1) |
| Modeled / not-for-construction disclaimer on every drawing surface | **COMPLETE** | Verified in §3 of `VALIDATION_SUMMARY.txt`. |
| Claude Code Handoff Package | **COMPLETE** | Authored; on disk. |

### Audit & ticketing
| Item | Class | Note |
|---|---|---|
| Reconciliation audit (file-level) | **COMPLETE** | [killdeer_reconciliation_audit.md](docs/implementation/killdeer_reconciliation_audit.md), 315 lines, dated 2026-06-06. |
| Audit performed **before** the implementation ticket | **MISSING** | Sequencing inversion (§3). |
| Smallest-safe implementation ticket as defined by the audit (sync 3D fallback + Spline contract to 25 nodes — findings S-1/S-2/S-3) | **MISSING** | The shipped ticket (PR #103, CMP overlay) is a different, larger one. The audit-recommended ticket has **not** been done. |

### Implementation (testbed-kit)
| Item | Class | Note |
|---|---|---|
| Flag-gated CMP overlay (`src/api/process_assets.py`) | **COMPLETE** | Read-only overlay; never touches SQLite registry/seed; falls back to `[]` on any error. |
| `PROCESS_ASSETS_ENABLED` config flag (default False) | **COMPLETE** | `src/config.py`. |
| `/process` demo-facility allowlist (`_DEMO_FACILITIES`) | **COMPLETE** | `src/api/twin.py`; non-demo facilities now 404 instead of leaking simulated data as real telemetry. |
| Tests for overlay + demo-gate | **COMPLETE** | `tests/test_process_assets.py` (+95), `tests/test_twin.py` (+12). 47 tests pass per PR message. |
| Production deploy (flag-off) | **COMPLETE** | Merge commit `8a501eb`. |
| Controlled validation with flag-on in non-prod | **MISSING** | Plan step 6 never executed. |
| Production enablement (flag flip) | **DEFER** | Should not happen yet. See §7. |

### Platform reconciliation findings (from the audit)
| Item | Class | Note |
|---|---|---|
| 25-node / 26-edge contract honored by `_TOPOLOGY` | **COMPLETE** | Pinned by `tests/test_twin.py:25-27`. |
| Asset registry covers process equipment | **PARTIAL** | 7-row lab fleet only; ~17 process nodes bind to `RTU-01` (finding A-1). |
| 3D offline fallback (`aevus-killdeer-3d.js` EQUIP array) | **PARTIAL** | 15 IDs; missing DEHY/VRU/CMB/SWD/FGS/ESD/LACT/WM/M2-* (finding S-1). |
| Spline binding harness ASSET_IDS | **PARTIAL** | 15 IDs (finding S-2). |
| Spline authoring contract (§1 table) | **PARTIAL** | 15 IDs, old labels (finding S-3). |
| Drawing access from the app | **MISSING** | No link/tab/per-asset reference (finding L-1). |
| `TwinNode.drawing_refs` (per-node drawing pointers) | **MISSING** | No analogous field (finding L-2). |
| Modeled/simulated banner on dashboard chrome | **MISSING** | Map/Overview have no on-screen disclaimer (finding T-2). |
| `_TOPOLOGY.origin` geographic alignment | **RISK** | Texas coordinates while field name and breadcrumb say North Dakota (finding K-1). |
| `topology.html` `assetToNode` parallel map | **RISK** | Independent hardcoded lab-network map; refactor hazard (finding D-1). |
| `drawings/VALIDATION_SUMMARY.txt` 26/27 vs. live 25/26 | **RISK** | Stale doc; Rev A bundle should not be re-shipped without a re-validation decision (finding V-1). |
| Marketing-site Killdeer surface | **DEFER** | aevus_io has zero references; intentional unknown (finding U-1). |
| Per-process-node asset schema (`Asset.type` grows past lab types) | **DEFER** | Real SCADAPack point-map work prerequisite (finding A-1). |

---

## 5. Platform Reconciliation Audit

Verbatim against the user-specified comparison axes. Where details belong to a single source of truth, this section cites the audit doc rather than restating it.

| Axis | Killdeer source of truth | Current platform state | Match? |
|---|---|---|---|
| 25-node / 26-edge topology | `_TOPOLOGY` in [src/api/twin.py](AEVUS_filesv2/testbed-kit/src/api/twin.py); drawings PFD = 19 process / P&ID = 20 process equipment as the process subset of those 25 nodes. | `_TOPOLOGY` = 25 nodes / 26 edges; pinned by [tests/test_twin.py:25-27](AEVUS_filesv2/testbed-kit/tests/test_twin.py). | ✅ at the API. ⚠️ 3 dashboard sidecars (S-1/S-2/S-3) still hardcoded to the old 15-ID roster. |
| Asset IDs | Drawing register cites `twin.py` node IDs. | Node IDs unique, match drawings (N-1/N-2). Asset registry has only the 7-row **lab fleet**; process nodes bind through `asset_id` to `RTU-01` (~17 nodes) or `RAD-01`. | ⚠️ IDs match; asset-row coverage does not (A-1). |
| Process overview | Drawings PFD + P&ID at A3 landscape; modeled-disclaimer on every sheet. | `/api/v1/twin/facility/{id}/process` returns `ProcessSnapshot` (stages of `ProcessReading{label, value, unit, status, reg}`); header marked SIMULATED DEMO DATA ONLY ([twin.py:462](AEVUS_filesv2/testbed-kit/src/api/twin.py:462)). After PR #103 the route 404s outside `_DEMO_FACILITIES`. | ✅ |
| Telemetry model | Drawing P&ID points carry SCADAPack-470 Modbus addresses (◎). Vitals expected per node. | Two surfaces — per-asset `VitalSign[]` keyed by **label** (no node/tag); `/process` carries `reg` (Modbus address) but no `node_id`. 17 of 25 nodes share `asset_id="RTU-01"`. | ⚠️ Bridge exists at `reg`, but node-level telemetry binding is absent. |
| Alarm model | Drawings imply per-node alarms (e.g. ESD interlock on the wellhead SSV, dewpoint at DEHY, vibration on CMP). | `Alert.asset_id` only — no `node_id`, `edge_id`, or `tag_id`. ISA-18.2 §11 shelving keyed on `(asset_id, metric_label)`. Most alarms land on `RTU-01`. | ⚠️ ISA-18.2-compliant model; binding density is the gap. |
| Health model | Per-asset health 0–100; field rollup. | `Asset.health: int \| None`; `/api/v1/health/summary`, `/trend`, `/ping`; fleet rollup = mean of non-null per-asset scores ([health.py:12-59](AEVUS_filesv2/testbed-kit/src/api/health.py)). | ✅ at the lab-fleet level. Per-process-node health is a derivative of `RTU-01`'s score. |
| Spline / 3D object mapping | Drawing register names each piece of equipment (drawing-aligned labels). | Procedural three.js twin in `aevus-killdeer-3d.js` has typed builders for all 25 node types; **offline fallback EQUIP array hardcodes only 15** (S-1). Spline harness `ASSET_IDS` = 15 (S-2). `SPLINE_TWIN_AUTHORING_CONTRACT.md` §1 = 15 + old labels (S-3). | ⚠️ Healthy-API path covers 25. Two dormant fallback/authoring surfaces and one contract doc still on 15. |
| Drawing package access from the app | Drawings exist as standalone HTML + PDFs in `drawings/` with a per-file SHA-256 in `VALIDATION_SUMMARY.txt`. | **No path from the app to the bundle.** No sidebar entry, no per-asset tab, no breadcrumb, no Sites-page link. `grep -ri "KD-PFD\|KD-PID\|KD-PLOT\|KD-ISO\|Rev A" src/ dashboard/` is empty. (L-1, L-2) | ❌ |
| Modeled / simulated disclaimers | "MODELED DIGITAL TWIN REFERENCE — NOT FOR CONSTRUCTION" on every drawing surface; `/process` endpoint header SIMULATED DEMO DATA ONLY. | Drawings ✅. `/process` ✅. `/topology` + `/flow` — only an implicit comment-level guard. Dashboard chrome (Map / Overview) — **no on-screen modeled banner** (T-2). Marketing site has "MODELED" badges but the marketing site does not surface Killdeer. | ⚠️ Endpoint-level coverage is solid; UI chrome is incomplete. |

---

## 6. Recommended Next Tickets

In strict order. Each is a single PR; none flips `PROCESS_ASSETS_ENABLED`; none copies drawings into the app.

### Ticket K-T1 — Sync the 3D offline fallback + Spline contract to the 25-node twin

- **Goal:** Eliminate the 15-vs-25 divergence in the only three places the app contradicts the Rev A contract: the procedural-3D offline fallback, the dormant Spline harness ID list, and the Spline authoring contract.
- **Files likely touched:**
  - [AEVUS_filesv2/testbed-kit/dashboard/aevus-killdeer-3d.js](AEVUS_filesv2/testbed-kit/dashboard/aevus-killdeer-3d.js) (extend EQUIP array, ~lines 81–97; optional `_TOPO_CACHE_KEY` bump v18→v19).
  - [AEVUS_filesv2/testbed-kit/dashboard/aevus-spline-twin.js](AEVUS_filesv2/testbed-kit/dashboard/aevus-spline-twin.js) (extend ASSET_IDS, ~line 41).
  - [AEVUS_filesv2/testbed-kit/docs/SPLINE_TWIN_AUTHORING_CONTRACT.md](AEVUS_filesv2/testbed-kit/docs/SPLINE_TWIN_AUTHORING_CONTRACT.md) (§1 table → 25 rows + drawing-aligned labels).
- **Files NOT to touch:** `src/api/twin.py`, `tests/test_twin.py` (the 25/26 lock), `src/main.py`, `src/api/assets.py`, `src/api/alerts.py`, `src/api/health.py`, `src/models/*`, `dashboard/topology.html`, anything under `drawings/`, anything under `aevus_io/`.
- **Acceptance criteria:**
  - All 25 IDs present in the EQUIP fallback with the same `(id, lng, lat, type, name)` shape, values copied verbatim from `_TOPOLOGY.nodes`.
  - All 25 IDs present in `ASSET_IDS`.
  - Authoring contract §1 table has 25 rows with drawing-aligned labels (e.g. "Condensate Tank #1", "Field Sales Compressor", "Meter Run — Custody (Sales)").
  - `tests/test_twin.py` still green (no change expected).
  - Healthy-API path is byte-identical (fallback only fires when `/topology` is unreachable).
- **Risk:** LOW. Fallback + authoring surfaces only; no request-path change; no schema change.

### Ticket K-T2 — Refresh `drawings/VALIDATION_SUMMARY.txt` against the live twin

- **Goal:** Resolve V-1. The drawings themselves are correct; the validation footer is stale (26/27 → 25/26). Either re-run the validation script against current `twin.py` and re-commit the summary under the same `rev-A` artifact, or document the drift as a known footnote — depending on the answer to blocking question 3 in the audit.
- **Files likely touched:** [drawings/VALIDATION_SUMMARY.txt](drawings/VALIDATION_SUMMARY.txt) only.
- **Files NOT to touch:** any drawing HTML/PDF in [drawings/](drawings/) (drawings did not change), the handoff zip (would need re-zipping under a new artifact name), [drawings/REVISION_NOTE.txt](drawings/REVISION_NOTE.txt) (rev unchanged), anything in testbed-kit or aevus_io.
- **Acceptance criteria:**
  - Node/edge counts match the live `_TOPOLOGY`.
  - PDF SHA-256s in §5 unchanged (since drawings did not change).
  - PASS line still correct.
- **Risk:** LOW. Docs-only in a separate repo.

### Ticket K-T3 — Add a dashboard "modeled / not for construction" banner on Killdeer surfaces

- **Goal:** Resolve T-2. Bring the dashboard chrome into parity with the drawings' disclaimer policy before the drawings are ever linked from the app.
- **Files likely touched:**
  - [AEVUS_filesv2/testbed-kit/dashboard/Aevus_Console.html](AEVUS_filesv2/testbed-kit/dashboard/Aevus_Console.html) — pages `overview`, `map`, `sites` (the Killdeer-facing pages).
- **Files NOT to touch:** any backend route, any model, generic dashboard pages that are fleet-wide (alarms, assets, health, historian, network, etc.), the marketing site.
- **Acceptance criteria:**
  - A visible, non-dismissable (or session-dismissable) banner on the three Killdeer-facing pages reading "Modeled digital twin — simulated demo data — not for construction".
  - Color / typography aligned with the existing dashboard chrome.
  - No behavioral change to data fetches.
- **Risk:** LOW. Pure UI text in HTML/CSS.

### Ticket K-T4 — Controlled validation harness for `PROCESS_ASSETS_ENABLED=1`

- **Goal:** Execute the missing plan-step-6 validation **without** a production flip. Stand up a documented procedure (and a one-pager artifact) for exercising the flag in a non-prod surface and observing `/assets`, `/twin/facility/killdeer/process`, the dashboard Overview / Map, and the CMP asset card.
- **Files likely touched:**
  - New: `docs/implementation/killdeer_process_assets_validation.md` — preconditions, steps, expected output, rollback (unset env), known limitations.
  - Optional: `tests/test_process_assets.py` extension to cover the `_worst()` precedence (good < warn < bad) and the `[]`-on-error path under simulated RTU absence.
- **Files NOT to touch:** `src/config.py`, `src/api/process_assets.py`, `src/api/assets.py`, `src/api/twin.py` (production-safe path is already merged; do not edit).
- **Acceptance criteria:**
  - Procedure runnable locally with `PROCESS_ASSETS_ENABLED=1` against a dev server; CMP asset visible on `/api/v1/assets` with vitals from the simulated SCADAPack-470 register set.
  - Rollback path documented (unset env, restart).
  - Validation evidence (curl outputs, screenshots if any) attached to the PR.
- **Risk:** LOW. Documentation + optional test additions only.

### Ticket K-T5 — `TwinNode.drawing_refs` (per-node drawing pointers) — **schema design only**

- **Goal:** Resolve L-2 at the design level — agree on a shape for `TwinNode.drawing_refs` (or an out-of-band lookup table) without yet implementing it.
- **Files likely touched:** new `docs/implementation/killdeer_drawing_refs_design.md`.
- **Files NOT to touch:** `src/api/twin.py`, `src/models/asset.py`, any frontend.
- **Acceptance criteria:**
  - Decision recorded for: (a) inline field on `TwinNode` vs. sidecar JSON; (b) URL shape for drawing references (`KD-PID-001#tag` vs. `KD-ISO-NNN`); (c) where the drawing bundle is served from (in-app `/drawings/` mount vs. external).
  - Trade-offs vs. the L-1 ticket (drawing surface in the dashboard) documented.
- **Risk:** LOW. Design doc only.

### Ticket K-T6 — DEFERRED: link Rev A drawings from the dashboard (L-1)

- **Goal:** Wire the dashboard to the Rev A bundle once K-T5's design decision is in.
- **Why deferred:** depends on K-T5 (sidecar shape) and K-T3 (banner exists on chrome). Do not start until both have landed.

### Tickets NOT recommended now (DEFER beyond this checkpoint)

- Flipping `PROCESS_ASSETS_ENABLED=1` in production.
- Expanding `Asset.type` Literal to include process types (per-process-node asset rows) — finding A-1; needs the real SCADAPack point map.
- Resolving `_TOPOLOGY.origin` Texas/ND drift (K-1) — needs an explicit business decision before any "real-map" feature surfaces.
- Anything in [aevus_io/](aevus_io/) for Killdeer — finding U-1; not in scope until the marketing decision is made.
- Touching [dashboard/topology.html](AEVUS_filesv2/testbed-kit/dashboard/topology.html) — finding D-1; lab-network page, unrelated.

---

## 7. Immediate Stop / Go Recommendation

### STOP — do not do any of these next

- ⛔ **Do not flip `PROCESS_ASSETS_ENABLED` anywhere** — production, staging, or local default. Plan step 6 (controlled validation) has not been performed. The flag must stay false until K-T4 is done.
- ⛔ **Do not deploy** anything Killdeer-shaped from testbed-kit. `main` is already at `8a501eb` flag-off; that is the correct posture.
- ⛔ **Do not copy or move the drawings** into the testbed-kit app yet (no `dashboard/drawings/` directory, no static-mount, no inlined PDFs). The Rev A bundle stays in [drawings/](drawings/) until K-T5 chooses the integration shape.
- ⛔ **Do not modify `src/api/twin.py` `_TOPOLOGY`, `tests/test_twin.py`, `src/api/process_assets.py`, `src/api/assets.py`, or `src/config.py`.** The 25/26 contract and the dormant overlay are correct; further edits in this layer would invalidate the audit baseline.
- ⛔ **Do not refactor.** No reshuffling of routers, no rename of `_FACILITY_ALIASES`, no schema changes to `Asset` or `Alert`.
- ⛔ **Do not delete any files**, including any of the 40+ unpushed local branches in testbed-kit — they are out of scope here.
- ⛔ **Do not start work on the marketing site (aevus_io)** for Killdeer (finding U-1 unanswered).
- ⛔ **Do not start the L-1 drawings-in-dashboard ticket (K-T6) yet.** K-T5 (design) and K-T3 (banner) must land first.

### GO — in this order, one at a time

1. **K-T1** — sync the 15-ID fallback/contract surfaces to the 25-node twin. This is the actual smallest-safe-ticket identified by the audit and the cleanest way to retire the only contradictions the audit found in the app.
2. **K-T2** — refresh `drawings/VALIDATION_SUMMARY.txt` (or document the footnote). Closes V-1.
3. **K-T3** — add the modeled/not-for-construction banner to the three Killdeer dashboard pages. Closes T-2 and is a prerequisite to ever linking the drawings.
4. **K-T4** — controlled-validation harness for `PROCESS_ASSETS_ENABLED=1`. Run plan step 6 against the already-deployed flag-off path. **No flag flip in prod.** The deliverable is a documented procedure + evidence + rollback note, not an env change.
5. **K-T5** — design doc for `TwinNode.drawing_refs` (or sidecar). No code.

After K-T5 is accepted, this document should be revisited before opening K-T6 (drawings-in-dashboard). Production enablement of `PROCESS_ASSETS_ENABLED` is **out of scope for this entire sequence** and should be its own program-control checkpoint.

---

## Open / unverified items (UNKNOWN)

- **V-1 — drawings validation drift.** Whether to re-issue `VALIDATION_SUMMARY.txt` under `rev-A` (re-validating against current `twin.py`) or to accept the drift as a historical footnote. UNKNOWN until business decision.
- **K-1 — Killdeer geographic origin.** `_TOPOLOGY.origin = (-95.8685, 29.3396)` is Texas; the field is named for Killdeer, ND. Whether this is intentional (modeled coordinates) or a defect blocks any future basemap work. UNKNOWN until business decision.
- **U-1 — marketing-site Killdeer surface.** Whether [aevus_io/](aevus_io/) should reference the Rev A pilot at all. UNKNOWN until business decision.
- **A-1 — per-process-node asset rows.** Whether `Asset.type` should grow past lab hardware types (radio/rtu/switch/router/sensor/edge/efm) to include process types (separator, compressor, heater, …). UNKNOWN until real SCADAPack point-map work is scoped.
- **Controlled-validation evidence for the flag-on path.** None on disk. UNKNOWN until K-T4 is executed.
- **PR #103 production smoke-test artifacts.** The user stated smoke tests passed; the artifacts themselves are not in this repo. UNKNOWN as on-disk evidence — accepted on user statement.
