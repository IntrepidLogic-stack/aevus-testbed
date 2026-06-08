# Killdeer Field — `drawing_refs` Schema Design (K-T5)

**Date:** 2026-06-08
**Ticket:** K-T5 (reconciliation roadmap)
**Type:** Design-only document — **no code, no schema change, no implementation**
**Resolves audit finding:** L-2 (`TwinNode.drawing_refs` missing)

---

## 1. Purpose and audit context

K-T5 resolves audit finding **L-2** ("`TwinNode.drawing_refs` per-node drawing
pointers — MISSING") at the **design level only**. It records the chosen
shape, location, and hosting posture for per-node drawing references, plus
the trade-offs that follow when K-T6 (audit finding L-1, "drawing access from
the app") wires the dashboard to the Rev A bundle.

This document **does not**:

- Add fields to `TwinNode`, `TwinEdge`, or any other Pydantic model.
- Create a sidecar JSON file. The sidecar's *shape* is proposed here; its
  *content* is K-T6 work.
- Touch `_TOPOLOGY` in `src/api/twin.py`.
- Add a frontend surface that links drawings.
- Copy drawing artifacts (HTML / PDF / ZIP) into the platform repo.
- Change deployment behavior.
- Flip `PROCESS_ASSETS_ENABLED`.

It exists so the K-T6 implementer has the three blocking design questions
already answered (and reviewed) before the first line of dashboard code lands.

---

## 2. Current baseline

| Item | State at K-T5 authoring time |
|---|---|
| Aevus platform `main` | `363c2df` — includes K-T1 (PR #104), K-T3 (PR #107), K-T4 (PR #108). K-T2 lives in the drawings repo, not here. |
| `_TOPOLOGY` shape | 25 `TwinNode` / 26 `TwinEdge` (pinned by `tests/test_twin.py:25-27`). |
| `_TOPOLOGY` node IDs | `WH, CHE, HTR, SEP, CMP, DEHY, VRU, FGS, OT1, OT2, PWT, SWD, WM, EFM, LACT, CMB, FLR, ESD, RTU, PWR, SOL, COM, TWR, M2-KO, M2-EFM`. |
| Drawings repo (`IntrepidLogic-stack/killdeer-drawings`) | `main` @ `836b072`. Tag `rev-A` immutable at `0d1e292`. Tag `rev-A.1` at `836b072` is the erratum for `VALIDATION_SUMMARY.txt` topology count only. |
| Rev A drawing artifacts | HTML (5 sheets), PDF (6 files), and `Killdeer_Field_Digital_Twin_Handoff_Rev_A.zip` are **byte-for-byte unchanged** from `rev-A` — the K-T2 erratum did not alter any drawing. The `VALIDATION_SUMMARY.txt §5` SHA-256s remain authoritative for HTML/PDF artifacts. |
| Modeled-reference banner (K-T3) | Live on Overview / Map / Sites in `dashboard/Aevus_Console.html`. **Any K-T6 surface that links a drawing must keep this banner visible.** |
| Process-asset overlay (PR #103) | Deployed dormant. `PROCESS_ASSETS_ENABLED` defaults to `False`. K-T5 has no interaction with the flag. |
| Authenticated production smoke | Still BLOCKED until a safe API key is sourced (cross-reference `pr104_post_merge_deployment_note.md` §8 and `killdeer_process_assets_validation.md` §10). Unrelated to K-T5. |

---

## 3. Source drawing set

The Rev A drawing package contains five drawings published by the
`killdeer-drawings` repo (Rev A authored 2026-06-06, erratum at Rev A.1):

| Drawing ID | Title | Type | Sheets | HTML | PDF (relative to `drawings/`) |
|---|---|---|---|---|---|
| `KD-DRAWING-REGISTER` | Drawing Register / Index | Index | 1 | `Killdeer_Drawings.html` | `exports/KD-DRAWING-REGISTER.pdf` |
| `KD-PFD-001` | Process Flow Diagram | PFD | 1 | `Killdeer_PFD.html` | `exports/KD-PFD-001_Process_Flow_Diagram.pdf` |
| `KD-PID-001` | Piping & Instrumentation Diagram (Level B) | P&ID | 1 | `Killdeer_PID.html` | `exports/KD-PID-001_Piping_Instrumentation_Diagram.pdf` |
| `KD-PLOT-001` | Plot Plan / General Arrangement | GA (plan) | 1 | `Killdeer_Plot.html` | `exports/KD-PLOT-001_Plot_Plan_GA.pdf` |
| `KD-ISO-001` | Piping Isometric Set | ISO set | **5** | `Killdeer_Iso.html` (with `?sheet=ISO-NNN` selector) | `exports/KD-ISO-001_Piping_Isometric_Set.pdf` (one PDF, 5 pages) |

`KD-ISO-001` is a five-sheet set; sheets are addressable individually:

| Sheet | Scope |
|---|---|
| `ISO-001` | Wellhead → Heater |
| `ISO-002` | Separator → Compressor |
| `ISO-003` | Compressor → Custody |
| `ISO-004` | Relief / Flare header |
| `ISO-005` | Condensate → LACT |

Per `drawings/VALIDATION_SUMMARY.txt §2` (Rev A.1 corrected copy): every
drawing node resolves to a real `TwinNode` in `src/api/twin.py`; PFD covers
19 / 19 process nodes, P&ID covers 20 / 20 process nodes. Non-process nodes
(RTU / COM / TWR / PWR / SOL) are intentionally omitted from PFD/P&ID and
appear only on the Plot Plan.

---

## 4. Decision A — inline `TwinNode.drawing_refs` vs. sidecar JSON

**Recommendation: sidecar JSON.**

### Trade-off table

| Aspect | Inline (`TwinNode.drawing_refs` field) | Sidecar JSON (recommended) |
|---|---|---|
| Live API schema | Adds a field to `/api/v1/twin/.../topology` wire contract | Untouched — `_TOPOLOGY` payload byte-identical |
| Pydantic model change | Requires editing `TwinNode` + tests | None |
| Cadence coupling | Every drawing revision touches `src/api/twin.py` | Drawing revs live in the drawings repo, where they belong |
| Source-of-truth ownership | Platform repo owns drawing IDs | Drawings repo owns drawing IDs |
| Rev tracking | Requires storing `drawing_package_rev` in the platform | Sidecar carries `drawing_package_rev` natively |
| K-T6 risk surface | Backend + frontend + tests | Frontend (or build-time) consumption of one JSON |
| Rollback if K-T6 is later un-shipped | Requires a schema migration | Stop fetching the sidecar |
| Multi-rev support (Rev A.1 vs Rev B) | Either fork the model or version the field | Sidecar versioned by URL or by inline `drawing_package_rev` |
| Authentication implications | Already protected by API auth | Either public (external host) or wrapped by a new auth surface |

### Why sidecar

- **Avoids live API schema change.** `/topology` stays exactly the same; the
  `tests/test_twin.py 25/26` lock is unaffected.
- **Avoids `TwinNode` / Pydantic model change.** No model migration, no new
  field validators, no test churn.
- **Keeps drawing revision cadence separate from topology.** When Rev B
  ships, the sidecar updates in the drawings repo; `src/api/twin.py`
  doesn't move.
- **Lets the drawings repo own the drawing-reference source of truth.** The
  drawings repo already owns `KD-PFD-001`, `KD-PID-001`, `VALIDATION_SUMMARY.txt`,
  and the `rev-A`/`rev-A.1` tags. The sidecar belongs alongside them.
- **Makes K-T6 lower risk.** K-T6 becomes "fetch one JSON and render link
  cards" — no backend, no model, no schema migration. If K-T6 needs to be
  reverted, removing the fetch is the whole rollback.

### Why not inline (yet)

Inline is a defensible future direction once the platform consumes the
sidecar at runtime *and* a long-term decision has been made that drawing
references are first-class topology metadata (rather than a delivered
artifact). K-T5 does not foreclose that future; it just doesn't take it now.

---

## 5. Decision B — URL / reference shape

**Recommendation: structured object, not raw string.**

### Comparison

| Shape | Example | Problems |
|---|---|---|
| Raw string | `"KD-PID-001#tag-CMP-001"` | Ambiguous between drawing-id and drawing-id-plus-fragment. No room for `title`, `rev`, `sheet`, or `kind`. Brittle to a Rev B that changes anchor naming. |
| Drawing-id + URL fragment | `"KD-PID-001#tag-CMP-001"` (parsed) | Same ambiguity as above; adds parser code in the frontend. |
| Structured object (recommended) | see below | Slightly more verbose; carries every field the dashboard needs without parsing. |

### Proposed object shape

A `drawing_ref` is a single reference; a `node_refs[node_id]` is an array of
`drawing_ref` objects.

```json
{
  "node_id": "CMP",
  "refs": [
    {
      "drawing_id": "KD-PFD-001",
      "title": "Process Flow Diagram",
      "rev": "A.1",
      "href": "Killdeer_PFD.html",
      "anchor": "node-CMP",
      "sheet": null,
      "kind": "process"
    }
  ]
}
```

### Field semantics

| Field | Required | Type | Meaning |
|---|---|---|---|
| `drawing_id` | yes | string | One of the five `KD-…` IDs from §3. |
| `title` | yes | string | Human-readable label for the dashboard card. |
| `rev` | yes | string | Revision tag the reference is valid against (e.g. `"A"`, `"A.1"`, `"B"`). Used to gate stale-reference warnings. |
| `href` | yes | string | Relative URL into the drawings repo (resolved against the chosen host root from Decision C). |
| `anchor` | optional | string \| null | URL fragment (without the `#`) inside the target HTML. `null` if no in-sheet anchor exists yet. |
| `sheet` | optional | string \| null | ISO sheet identifier (e.g. `"ISO-002"`); used by `KD-ISO-001`. `null` for single-sheet drawings. The renderer composes `href` + `?sheet=<sheet>` when present. |
| `kind` | yes | enum | One of `process` (PFD), `pid`, `plot`, `iso`, `register`. Drives card iconography and grouping. |

### PID example (uses anchor)

```json
{
  "drawing_id": "KD-PID-001",
  "title": "Piping & Instrumentation Diagram",
  "rev": "A.1",
  "href": "Killdeer_PID.html",
  "anchor": "tag-CMP-001",
  "sheet": null,
  "kind": "pid"
}
```

### ISO example (uses sheet selector)

```json
{
  "drawing_id": "KD-ISO-001",
  "title": "Piping Isometric — Separator → Compressor",
  "rev": "A.1",
  "href": "Killdeer_Iso.html",
  "anchor": null,
  "sheet": "ISO-002",
  "kind": "iso"
}
```

The dashboard composes the final URL as
`<host_root>/<href>?sheet=<sheet>#<anchor>`
with each segment omitted when its field is `null`. This matches
`Killdeer_Iso.html`'s existing `?sheet=` selector (verified at K-T2 time).

---

## 6. Decision C — drawing hosting

**Recommendation: external static hosting for the first K-T6 wire-up.**

### Options

| Option | Description | Pros | Cons |
|---|---|---|---|
| **External static — GitHub Pages on the drawings repo** | Enable GitHub Pages on `IntrepidLogic-stack/killdeer-drawings`, serving the `main` branch (Rev A.1 corrected) at `https://intrepidlogic-stack.github.io/killdeer-drawings/`. | No new infra, ties hosting to the tagged repo, immutable Rev A artifact stays the source of truth. | Public URL — only acceptable for modeled / no-IP content. |
| **External static — S3 + CloudFront** | Sync the drawings repo to an S3 bucket on `rev-*` tag releases, front with CloudFront. | Versionable, supports auth via signed URLs if needed, fits the existing AWS posture. | New infra, deploy automation needed, more moving parts to keep in sync with the tagged repo. |
| In-app `/drawings/*` mount | FastAPI `StaticFiles` mount over a checked-out copy of the drawings repo, served at `https://aevus.intrepidlogic.io/drawings/`. | Reuses existing auth (`X-API-Key` middleware) for free. | Couples drawing artifact storage to the platform deploy; immutable `rev-A` SHA chain now becomes a concern of the platform repo; requires a sync mechanism. |
| Snapshot copied into `dashboard/public assets` | Copy HTML/PDF/zip into `dashboard/drawings/` and serve as static files. | Simplest URL story — same origin. | **Explicitly forbidden by every Killdeer prompt in this sequence** — no drawing copy into the platform repo. Breaks the Rev A immutability and the rev-A.1 erratum contract. |

### Why external first

- **Rev A immutability is preserved.** The artifacts stay under the
  drawings repo's `rev-A`-pinned commit. The platform never owns a
  drawing byte.
- **No new auth/CDN policy is required to start K-T6.** The drawings
  package has always been authored as a publicly hand-offable artifact
  with a "MODELED — NOT FOR CONSTRUCTION" disclaimer on every sheet.
  Public hosting matches that posture.
- **Deploy decoupling.** The platform's `Deploy to EC2` step has no
  dependency on the drawings repo. K-T6's link surface is read-only;
  no platform deploy is needed to ship a drawing rev.
- **Cheapest reversal.** If K-T6 needs to be un-shipped, removing the
  dashboard's link surface is the whole rollback; nothing else changes.

### Why in-app is the longer-term option

In-app hosting becomes attractive if and when:

- A future pilot needs IP-sensitive drawings hidden behind the platform's
  existing auth.
- A future viewer (zoom-pan, layered overlays) needs sub-resource fetches
  that benefit from same-origin policy.
- Audit/logging requires that every drawing fetch be recorded under
  Aevus's own request log.

None of those apply to Rev A modeled drawings today. K-T5 explicitly
defers the in-app mount and recommends K-T6 ships with external hosting
first; an in-app mount can be re-scoped once the drawing-package
auth/CDN/IP-review policy has been written.

---

## 7. Recommended sidecar location

**Recommendation: drawings repo.**

| Aspect | Drawings repo (recommended) | Platform repo | Separate repo |
|---|---|---|---|
| Source-of-truth co-location | Same repo as the HTML/PDF the sidecar refers to | Drawings live elsewhere — drift risk | Drift risk x 2 |
| Rev tracking | Same tag (`rev-A`, `rev-A.1`, future `rev-B`) covers both drawings and sidecar | Platform rev != drawings rev | Yet another rev to track |
| Change cadence | Updates with the drawings | Updates whenever the platform releases | Independent |
| K-T6 fetch | One HTTP request against the external host | Same origin if in-app, otherwise platform must republish the sidecar | Another host |
| Review burden | A drawings-repo PR | A platform-repo PR (includes CI deploy) | A new-repo PR |

### Proposed path inside the drawings repo

```
killdeer-drawings/
├── …existing rev-A artifacts…
├── data/
│   └── killdeer_drawing_refs.json     ← K-T5 sidecar (created later)
```

### K-T5 does not create this file

The K-T5 deliverable is this design document. **The sidecar JSON is not
created by K-T5.** It is created in a follow-up drawings-repo PR (and
optionally rebased into a `rev-A.2` tag, by the same convention as `rev-A.1`)
once K-T5 is accepted.

---

## 8. Proposed sidecar schema

A complete schema sketch, suitable as the first version of
`data/killdeer_drawing_refs.json`. Field comments are illustrative;
the actual file would carry only JSON.

```json
{
  "version": 1,
  "site_id": "killdeer",
  "facility_id": "killdeer-bluejay-1",
  "drawing_package_rev": "A.1",
  "generated_from": "src/api/twin.py @ Aevus platform main; drawings @ IntrepidLogic-stack/killdeer-drawings rev-A.1",

  "disclaimer": "MODELED DIGITAL TWIN REFERENCE — NOT FOR CONSTRUCTION. All values are simulated / demo-only. Refer to VALIDATION_SUMMARY.txt and REVISION_NOTE.txt for the licensed-PE responsibilities.",
  "modeled_not_for_construction": true,

  "drawings": [
    { "drawing_id": "KD-DRAWING-REGISTER", "title": "Drawing Register / Index", "href": "Killdeer_Drawings.html", "kind": "register" },
    { "drawing_id": "KD-PFD-001", "title": "Process Flow Diagram", "href": "Killdeer_PFD.html", "kind": "process" },
    { "drawing_id": "KD-PID-001", "title": "Piping & Instrumentation Diagram", "href": "Killdeer_PID.html", "kind": "pid" },
    { "drawing_id": "KD-PLOT-001", "title": "Plot Plan / General Arrangement", "href": "Killdeer_Plot.html", "kind": "plot" },
    { "drawing_id": "KD-ISO-001", "title": "Piping Isometric Set", "href": "Killdeer_Iso.html", "kind": "iso",
      "sheets": ["ISO-001", "ISO-002", "ISO-003", "ISO-004", "ISO-005"] }
  ],

  "node_refs": {
    "CMP": [
      { "drawing_id": "KD-PFD-001", "title": "Process Flow Diagram", "rev": "A.1", "href": "Killdeer_PFD.html", "anchor": "node-CMP", "sheet": null, "kind": "process" },
      { "drawing_id": "KD-PID-001", "title": "Piping & Instrumentation Diagram", "rev": "A.1", "href": "Killdeer_PID.html", "anchor": "tag-CMP-001", "sheet": null, "kind": "pid" },
      { "drawing_id": "KD-ISO-001", "title": "Piping Isometric — Separator → Compressor", "rev": "A.1", "href": "Killdeer_Iso.html", "anchor": null, "sheet": "ISO-002", "kind": "iso" },
      { "drawing_id": "KD-PLOT-001", "title": "Plot Plan / General Arrangement", "rev": "A.1", "href": "Killdeer_Plot.html", "anchor": null, "sheet": null, "kind": "plot" },
      { "drawing_id": "KD-DRAWING-REGISTER", "title": "Drawing Register / Index", "rev": "A.1", "href": "Killdeer_Drawings.html", "anchor": null, "sheet": null, "kind": "register" }
    ]
    /* node_refs continues for every node id listed in §9 below */
  }
}
```

### Required top-level fields

| Field | Type | Meaning |
|---|---|---|
| `version` | int | Schema version. Start at `1`; increment on breaking shape changes. |
| `site_id` | string | Lowercased site key. For Killdeer: `"killdeer"`. |
| `facility_id` | string | Matches `_TOPOLOGY.facility_id`. For Killdeer: `"killdeer-bluejay-1"`. |
| `drawing_package_rev` | string | Revision tag of the drawing artifacts. Must match the `rev-*` tag of the drawings repo at generation time. |
| `generated_from` | string | Free-form provenance. Recommend including both the platform-repo commit (twin.py source) and the drawings-repo commit / tag. |
| `disclaimer` | string | The "MODELED — NOT FOR CONSTRUCTION" wording, verbatim from the drawing package. The dashboard must surface this where the link surface lands. |
| `modeled_not_for_construction` | bool | Programmatic flag. K-T6 surface code can branch on it for any future "real" drawings. |
| `drawings` | array | One entry per drawing in §3. Carries package-level metadata (no per-node detail). |
| `node_refs` | object | Map keyed by `TwinNode.id`. Value is an array of `drawing_ref` objects (shape from §5). |

### Anchors are optional

Anchor IDs (`anchor` fields) refer to HTML element IDs inside
`Killdeer_PFD.html` / `Killdeer_PID.html`. **Today's drawings do not
expose anchors.** Adding anchors is a separate drawings-repo follow-up
ticket — open question logged in §13. Sidecar entries created before
anchors land MUST use `"anchor": null` rather than invented IDs.

---

## 9. Per-node coverage matrix

The matrix below maps every `_TOPOLOGY.nodes[*].id` (all 25) to the
drawings expected to carry that node. `Y` = appears on the drawing per
the K-T2-corrected `VALIDATION_SUMMARY.txt §2`. ISO sheet assignments
follow the §3 sheet-scope table; entries marked **TBD** await drawing-author
confirmation and must NOT be invented at sidecar-creation time.

> **Reading rule:** an entry like `KD-PFD-001` means the node belongs on
> that drawing; the exact anchor inside the HTML is **TBD** until the
> drawings carry anchor IDs.

| Node | KD-PFD-001 | KD-PID-001 | KD-PLOT-001 | KD-ISO-001 (sheet) | KD-DRAWING-REGISTER |
|---|:---:|:---:|:---:|:---:|:---:|
| `WH` (Wellhead — BlueJay #1) | Y | Y | Y | ISO-001 | Y |
| `CHE` (Chemical Injection) | Y | Y | Y | TBD | Y |
| `HTR` (Line Heater / Inlet Scrubber) | Y | Y | Y | ISO-001 | Y |
| `SEP` (3-Phase Separator) | Y | Y | Y | ISO-002 | Y |
| `CMP` (Field Sales Compressor) | Y | Y | Y | ISO-002, ISO-003 | Y |
| `DEHY` (TEG Dehydrator) | Y | Y | Y | TBD | Y |
| `VRU` (Vapor Recovery Unit) | Y | Y | Y | TBD | Y |
| `FGS` (Fuel-Gas Conditioning Skid) | Y | Y | Y | TBD | Y |
| `OT1` (Condensate Tank #1) | Y | Y | Y | ISO-005 | Y |
| `OT2` (Condensate Tank #2) | Y | Y | Y | ISO-005 | Y |
| `PWT` (Produced Water Tank) | Y | Y | Y | TBD | Y |
| `SWD` (Water Disposal Pump) | Y | Y | Y | TBD | Y |
| `WM` (Produced-Water Meter) | Y | Y | Y | TBD | Y |
| `EFM` (Meter Run — Custody / Sales) | Y | Y | Y | ISO-003 | Y |
| `LACT` (Condensate LACT Unit) | Y | Y | Y | ISO-005 | Y |
| `CMB` (Enclosed Combustor) | Y | Y | Y | TBD | Y |
| `FLR` (Flare Stack) | Y | Y | Y | ISO-004 | Y |
| `ESD` (ESD / SIS Panel) | — | Y | Y | TBD | Y |
| `RTU` (PLC Shelter) | — | — | Y | — | Y |
| `PWR` (Power System) | — | — | Y | — | Y |
| `SOL` (Solar Array) | — | — | Y | — | Y |
| `COM` (Communications) | — | — | Y | — | Y |
| `TWR` (Radio Tower) | — | — | Y | — | Y |
| `M2-KO` (Sales-Station Inlet Scrubber) | Y | Y | Y | ISO-003 | Y |
| `M2-EFM` (Sales-Station Custody Meter) | Y | Y | Y | ISO-003 | Y |

**Counts (sanity check):** PFD column has 19 `Y`s (matches PFD = 19/19),
P&ID column has 20 `Y`s (matches P&ID = 20/20), Plot column has 25
(every node), Drawing-Register column has 25 (per-package index applies
to all nodes). ISO assignments are explicit where the §3 sheet-scope is
clear and `TBD` where the sheet boundary is ambiguous without drawing
inspection. Five non-process nodes (`RTU`, `PWR`, `SOL`, `COM`, `TWR`)
correctly appear on Plot and Register only.

---

## 10. K-T6 implications

K-T6 ("link Rev A drawings from the dashboard") starts only after K-T5
is reviewed and accepted. When K-T6 starts:

- **K-T6 ships an external link surface first, not an embedded viewer.**
  A card / drawer entry / per-asset "Drawings" tab is acceptable; an
  iframe or full SVG viewer is out of scope. Operators click out to the
  external drawings host (Decision C).
- **K-T6 keeps the K-T3 modeled banner visible.** No K-T6 surface
  (modal, drawer, full-screen viewer) may obscure or replace the banner.
  Where K-T6 adds a new tab/page that the banner does not naturally
  occupy, the same `.modeled-banner` element/text from K-T3 must be
  repeated there.
- **K-T6 does not require `PROCESS_ASSETS_ENABLED`.** The flag stays
  `False`. Drawing references are independent of the CMP overlay.
- **K-T6 does not mutate `TwinNode`.** The sidecar is consumed by the
  dashboard at runtime (or at build time); `TwinNode` stays as it is.
- **K-T6 consumes the sidecar shape from §5/§8.** The first cut may
  link only `KD-DRAWING-REGISTER` (package-level) from a single dashboard
  surface; per-node links land after the sidecar's `node_refs` is
  populated.
- **K-T6 must surface the `drawing_package_rev`.** The dashboard shows
  "Rev A.1" (or current rev) next to any drawing link, so an operator
  can see at a glance which version they're hitting.

---

## 11. Auth and access posture

- **External hosting (Decision C, recommended) avoids immediate Aevus
  auth coupling.** The drawings are already authored as
  modeled / not-for-construction; they do not encode pricing, tech
  stack, real telemetry, or proprietary algorithms. Public static
  hosting is consistent with the existing posture.
- **In-app hosting would require an auth/public decision.** If
  drawings later move under the platform's roof, the team must decide
  whether `/drawings/*` requires the same `X-API-Key` / session cookie
  as `/api/v1/*`, or whether it is intentionally public. K-T5 does not
  pick that policy; it defers it.
- **Modeled drawings may be public-safe only after IP / public-repo
  review.** Before pointing K-T6 at an external host, confirm the
  Killdeer Rev A bundle's IP review is on file (or run it). The Rev A
  package's `REVISION_NOTE.txt` already states "MODELED, SIMULATED,
  DEMO-ONLY — NOT FOR CONSTRUCTION"; the recommendation is consistent
  with that, but the decision is the business's.
- **Do not expose secrets, pricing, proprietary algorithms, or
  live-looking data via drawing artifacts.** Any future drawing
  artifact that does so must change hosting posture before being
  surfaced.

---

## 12. Out of scope

K-T5 is **explicitly design-only.** None of the following are part of K-T5:

- No code implementation.
- No `TwinNode` schema change.
- No sidecar JSON creation.
- No drawing copy into the platform repo.
- No dashboard UI change (no new card, drawer, tab, page, or banner).
- No API change.
- No CI / deploy workflow change.
- No flag default change.
- No `PROCESS_ASSETS_ENABLED` flip.
- No authenticated production smoke run.

These belong to K-T6 (and to a separate drawings-repo PR that creates the
sidecar) once this design is accepted.

---

## 13. Open decisions before K-T6

These remain for the business / reviewer to confirm. K-T6 should not start
until they are resolved (or explicitly accepted as deferred):

1. **Exact external host.** GitHub Pages on `killdeer-drawings`, S3 +
   CloudFront, or another? (Recommendation: GitHub Pages for the first
   wire-up — zero new infra; revisit if/when IP review demands signed URLs.)
2. **Sidecar location.** Confirm `killdeer-drawings/data/killdeer_drawing_refs.json`
   served from the same external host as the drawings themselves, vs. a
   separate copy under a controlled static host.
3. **Anchor implementation strategy.** Adding anchor IDs (e.g.
   `<g id="tag-CMP-001">`) to `Killdeer_PFD.html` and `Killdeer_PID.html`
   is a separate drawings-repo follow-up ticket. Until it lands, sidecar
   entries use `"anchor": null` and the dashboard links to the whole
   drawing.
4. **Link target — open in new tab, in-app drawer, or modal?**
   Recommendation: new tab. Keeps the dashboard's state intact, avoids
   in-app iframe security gymnastics, lets the operator return to the
   modeled-banner-bearing dashboard with a single tab close.
5. **First dashboard surface for the drawing link.** Sites page card?
   Per-asset drawer "Drawings" tab? A new top-level sidebar `Drawings`
   entry? Recommendation: start with the Sites page (single anchored
   card linking `KD-DRAWING-REGISTER`), then iterate to per-asset links
   once `node_refs` is populated.
6. **`rev-A.2` decision.** If/when the sidecar JSON is created in the
   drawings repo, should it land under a new tag (`rev-A.2`) following
   the K-T2 erratum convention, or as an `rev-A.1` amendment? Keeping
   `rev-A.1` immutable matches the K-T2 precedent; `rev-A.2` for the
   sidecar addition is the cleaner historical record.

---

## 14. Recommendation

**Recommended K-T6 path:**

- **External link first** — start by hosting drawings via GitHub Pages on
  `killdeer-drawings` (decision pending §13.1).
- **`KD-DRAWING-REGISTER` is the first target** — a single dashboard
  surface (Sites page card) links to the drawing register / index; from
  the index, the operator navigates to PFD / P&ID / Plot / Iso. This is
  the smallest possible first cut.
- **Sidecar JSON design reviewed before per-node links** — populate
  `node_refs` only after this design doc is accepted and the sidecar
  file is created in a separate drawings-repo PR.
- **No embedded viewer in the first pass** — links open in a new tab;
  the in-app drawing viewer (if ever) is a separate, later ticket.
- **No production flag flip** — `PROCESS_ASSETS_ENABLED` stays `False`.
  K-T5 / K-T6 are orthogonal to the CMP overlay.
- **K-T3 banner stays visible** — any surface that holds a drawing
  link inherits or repeats the modeled-banner disclosure.

---

## Appendix — relation to K-T1 / K-T2 / K-T3 / K-T4

| Ticket | What it gave us | How K-T5 builds on it |
|---|---|---|
| K-T1 (PR #104) | Aligned the dashboard's 3D fallback + Spline contract to the 25-node topology. | Confirms the node-ID universe (all 25 in §9) the sidecar must cover. |
| K-T2 (drawings-repo PR #1, tag `rev-A.1`) | Corrected the `VALIDATION_SUMMARY.txt` topology count without touching any drawing artifact. | Establishes `rev-A.1` as the rev string the sidecar's `drawing_package_rev` field should carry. |
| K-T3 (PR #107) | Added the modeled / not-for-construction banner on Overview / Map / Sites. | Pins the disclosure rule K-T6 must inherit on any drawing-link surface. |
| K-T4 (PR #108) | Documented the controlled local validation procedure for `PROCESS_ASSETS_ENABLED=1`. | Confirms `PROCESS_ASSETS_ENABLED` stays orthogonal to K-T5 / K-T6 — the design here does not flip or depend on the flag. |
