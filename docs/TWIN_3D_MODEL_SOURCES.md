# Killdeer Twin — 3D Model Sourcing (Path C)

Where to get a 3D model for each asset, cheapest → best. All "free" options below
are **CC0 / royalty-free** (safe to use commercially). Export/convert each to
**`.glb`** (glTF binary) — Spline and three.js both import it. Drag `.glb` into
Spline, or hand them to me for an r3f scene.

> Tip: filter Sketchfab by **Downloadable** + license **CC0**. Run heavy models
> through [gltf.report](https://gltf.report) or `gltf-transform` to Draco-compress
> before shipping (keeps the page fast).

| Asset (ID) | Search terms | Best free sources |
|---|---|---|
| Wellhead / pump jack (`WH`) | "pumpjack", "oil pump jack", "wellhead christmas tree" | Sketchfab (CC0), Poly Pizza |
| Gas-lift compressor (`CMP`) | "gas compressor skid", "industrial compressor", "engine skid" | Sketchfab, TurboSquid (free filter) |
| Line heater / scrubber (`HTR`) | "horizontal pressure vessel", "heater treater", "scrubber tank" | Sketchfab — reuse a horizontal-vessel model |
| Chemical injection (`CHE`) | "chemical tote", "IBC tank", "injection skid" | Poly Pizza ("IBC tank"), Sketchfab |
| 2-phase separator (`SEP`) | "horizontal separator vessel", "pressure vessel skid" | Sketchfab (CC0) |
| Flare stack (`FLR`) | "flare stack", "gas flare", "chimney + flame" | Sketchfab; add a flame in Spline |
| Oil / stock tanks (`OT1`,`OT2`) | "storage tank", "oil tank", "cylindrical industrial tank" | Poly Pizza, Quaternius, Sketchfab |
| Produced water tank (`PWT`) | same as oil tank, recolor | reuse the oil-tank model |
| EFM / custody meter (`EFM`) | "metering skid", "gas meter run", "pipe manifold skid" | Sketchfab; or build from pipe primitives |
| RTU / PLC shelter (`RTU`) | "small industrial building", "equipment shelter", "control cabin" | Poly Pizza, Quaternius, Kenney.nl |
| Radio tower (`TWR`) | "lattice tower", "communications tower", "radio mast" | Sketchfab (CC0), Poly Pizza |
| Power system (`PWR`) | "solar panel", "PV array", "battery cabinet" | Poly Pizza, Quaternius, Kenney.nl |
| Trees / ground (env) | "low poly trees", "pine tree pack", "ground rock" | **Quaternius** (great CC0 nature packs), Kenney.nl |

### Free model libraries (bookmark these)
- **Poly Pizza** — polypizza.com — fast, all CC0, one-click `.glb`.
- **Sketchfab** — sketchfab.com — biggest library; filter Downloadable + CC0.
- **Quaternius** — quaternius.com — CC0 low-poly packs (nature, industrial, props).
- **Kenney.nl** — kenney.nl — CC0 game-asset packs (buildings, props, solar).

### Paid (if you want photoreal fast)
- **TurboSquid** / **CGTrader** — search "oil gas facility", buy a pack; ~$20–150.
- **Commission a 3D artist** — Fiverr/Upwork, ~1–2 weeks for the full set matched
  to the render. Hand them the ChatGPT image as the spec.

### Two ways to use them
1. **Spline (Path B):** File → Import the `.glb` into your scene, name it with the
   asset ID (`WH`, `CMP`…), done.
2. **r3f (later):** send me the `.glb`s; I load them with `GLTFLoader` in a
   react-three-fiber scene, bound to the same live-data layer.

Whatever route, **the data binding is identical** — name/ID is the join key.
