# Spline Digital-Twin — Authoring Contract

**Status:** Draft v1 · 2026-06-04 · Owner: Woody

This is the rulebook for building the Killdeer Field 3D scene in **Spline** so it
plugs into the Aevus live-data binding harness and becomes a **real digital twin**,
not a static render. Build the *body* (geometry/materials/lighting) in Spline; the
harness binds *live data* to it by **stable asset ID** at runtime.

> **The one rule that makes it a twin:** the scene contains **zero data**. Every
> number, color, and status comes from the server at runtime, joined to geometry
> by the object's NAME = canonical asset ID. If you ever type a pressure/temp into
> Spline, it's a picture, not a twin.

---

## 1. Object naming (REQUIRED — this is how data binds)

Name the top-level object/group for each asset **exactly** one of these IDs
(case-sensitive). These match `src/api/twin.py` topology + the asset registry.

| Spline object name | Asset | Render label |
|---|---|---|
| `WH`  | Wellhead | WELLHEAD #1 |
| `CMP` | Gas-Lift Compressor | GAS LIFT COMPRESSOR |
| `HTR` | Line Heater / Scrubber | LINE HEATER / SCRUBBER *(new node)* |
| `CHE` | Chemical Injection | CHEMICAL INJECTION |
| `SEP` | 2-Phase Separator | 2-PHASE SEPARATOR |
| `FLR` | Flare Stack | FLARE STACK |
| `OT1` | Stock Tank #1 | STOCK TANK #1 |
| `OT2` | Stock Tank #2 | STOCK TANK #2 |
| `PWT` | Produced Water Tank | PRODUCED WATER TANK |
| `EFM` | EFM / Custody Meter | EFM / CUSTODY METER |
| `RTU` | RTU / PLC Shelter | RTU / PLC SHELTER *(new node)* |
| `TWR` | Radio Tower | RADIO TOWER |
| `PWR` | Power System (solar+battery) | POWER SYSTEM *(new node)* |
| `SOL` | Solar Array | SOLAR ARRAY *(new node)* |
| `COM` | Communications (VSAT/comms) | COMMUNICATIONS *(new node)* |

*(HTR / RTU / PWR will be added to the topology graph to match the render — confirm
the IDs above are fine and we'll register them.)*

**Rules**
- The asset's whole mesh group gets the ID name. Sub-parts can be named freely.
- Do **not** reuse an ID. Do **not** rename after we wire it.

---

## 2. Card anchors (where the floating data panel attaches)

For each asset, add a small **empty/null object** as a child, positioned where the
glassmorphic data card should float (usually top-right of the asset, like the
render). Name it `<ID>_anchor` — e.g. `CMP_anchor`, `SEP_anchor`.

The harness projects this anchor's world position to screen each frame and pins the
HTML card there, so the card tracks the asset as the camera orbits.

---

## 3. Pipes / flow (the glowing lines)

Pipes carry the live flow animation. Two options, easiest first:

- **Option A (simple):** model the pipe network as geometry with an **emissive
  material**; name the whole network `PIPES`. The harness pulses global flow color.
- **Option B (per-segment, richer):** name each pipe run by its topology edge id
  (`WH-CMP`, `CMP-SEP`, `SEP-OT1`, …). The harness then drives each segment's
  emissive intensity + flow speed independently from `/twin/flow` (normalized 0–1),
  and turns a segment red on a bad downstream status. This is the bind-by-ID flow we
  already run on the procedural twin.

Give pipe materials an **emissive channel** so status glow works. Cyan = normal,
amber = warn, red = fault (driven at runtime — don't bake).

---

## 4. Materials & status

Each bindable asset's primary material must expose an **emissive** input (color +
intensity). The harness sets it per live status:

| Status | Emissive |
|---|---|
| good / normal | teal `#06B6D4` (low glow) |
| warn | amber `#FBBF24` |
| bad / fault | red `#EF4444` (pulsing) |
| offline / unknown | desaturated, dim |

Optional: expose Spline **Variables** named `<ID>_status` (string) if you'd rather
drive a Spline state-machine than have us set materials directly. Either works; tell
us which and we bind accordingly.

---

## 5. Camera / interaction

- Add an **orbit** camera with an **auto-rotate** state (maps to the render's
  "Auto-rotate" toggle). The harness can start/stop it.
- A default framing that shows the **whole field including the Radio Tower** (the
  tower is tall — leave headroom; it was clipping in the MapLibre version).
- Keep zoom/orbit limits sane so users can't fly inside a tank.

---

## 6. Lighting / look (to match the render)

- HDRI/environment lighting + soft shadows.
- Bloom on emissive (the pipe glow + flare). Spline has a Bloom post effect.
- Flare Stack (`FLR`): an emissive flame (a small particle/animated material is fine).
- Ground diorama + trees are decorative — name them `ENV_*` so the harness ignores them.

---

## 7. Export / handoff

- Export as **Code → it produces a `.splinecode` URL** (and/or a React component).
  We use the **vanilla** `@splinetool/runtime` against the `.splinecode` URL so it
  drops into the current dashboard with no framework rewrite.
- Send the `.splinecode` URL (or the file). The harness loads it, finds objects by
  the IDs above, and binds live `/assets` + `/twin/flow` + `/health` + `/alerts`.

---

## 8. What the harness does (so you know the contract holds)

1. Loads the Spline scene into a `<canvas>` on the Map page "3D View".
2. `app.findObjectByName(ID)` for each asset → drives emissive from live status.
3. `/twin/flow` (poll/WS) → per-segment pipe flow + color.
4. Projects each `<ID>_anchor` → screen → pins the live HTML data card (vitals from
   `/assets`, bind-by-ID).
5. Production Summary, KPI bar, Active Alerts = DOM overlays from `/health` +
   `/assets` + `/alerts`.
6. Loading / stale-data / error / offline states handled by the harness (reuses the
   "Building digital twin" loader + stale-data patterns already shipped).

**Trade-secret + safety unchanged:** only normalized values (0–1 flow, coarse
status) reach the client; raw process values + scoring weights never leave the
server. IL-9000: the twin is read-only/advisory — it never commands a device.

---

## 9. Harness status & activation (2026-06-04)

The harness is **built and shipped, dormant**: `dashboard/aevus-spline-twin.js`.
It does nothing until a scene URL is provided, so it's safe to have deployed.

**To activate once you've exported from Spline (Export → Code → `.splinecode` URL):**

1. Add a mount point on the Map page (a 3D-View container):
   `<div id="aevus-spline-mount" style="position:absolute;inset:0;"></div>`
2. Reference the harness + set the scene URL, in `Aevus_Console.html`:
   ```html
   <script>window.AEVUS_SPLINE_URL = "https://prod.spline.design/XXXX/scene.splinecode";</script>
   <script src="/dashboard/aevus-spline-twin.js?v=1"></script>
   ```
   …or at runtime with no edit: `AevusSplineTwin.load("…/scene.splinecode")`.
3. **CSP caveat:** the harness imports `@splinetool/runtime` as an ESM from unpkg.
   If the dashboard CSP blocks it (it blocked the Cognito SDK once — Task #108),
   **vendor** the runtime: drop `runtime.js` into `/dashboard`, add it to the
   `deploy.sh` whitelist, and set `window.AEVUS_SPLINE_RUNTIME = "/dashboard/runtime.js"`.
4. `AevusSplineTwin.status()` reports `{sceneUrl, loaded, bound, anchors}` for debugging.

**What's wired now:** scene load, `findObjectByName(ID)` status binding (Spline
variable `<ID>_status` + best-effort emissive), `/twin/flow` per-segment binding
(`<edgeId>_flow` / `<edgeId>_status`), and live HTML data cards pinned to each
`<ID>_anchor`. The world→screen **anchor projection** is best-effort against the
vanilla runtime and will be finalized against the real exported scene (the
runtime abstracts three.js, so we confirm the camera/renderer access once the
`.splinecode` exists). Start with a 2-object test (e.g. `SEP` + `FLR` + their
anchors) so we can validate the binding end-to-end before you build the full field.
