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

---

## Purchase links — curated buy-list (2026-06-05)

Killdeer is a **land gas-lift wellsite** (Christmas-tree wellhead → separator →
compressor → tank battery → flare → custody meter). **Skip offshore/subsea
platform kits and giant refinery scenes** — pick individual land assets + one
vessel/refinery *collection* for the bulk.

### 🎯 Best "buy a bundle" picks (cover the most in one purchase)
- **TurboSquid Refinery collection** (~$51–75) — vessels, pipe racks, tanks, towers → https://www.turbosquid.com/3d-model/collection/refinery
- **TurboSquid Petroleum Refinery** (200+ models, FBX, filterable) → https://www.turbosquid.com/3d-model/petroleum-refinery
- **CGTrader "Oil tanks and flare stacks"** (tank battery + flare in one) → https://www.cgtrader.com/3d-models/industrial/industrial-machine/oil-tanks-and-flare-stacks

### 🔧 Per-asset (by asset ID)
| Asset | Link |
|---|---|
| **WH** Wellhead (Christmas tree) | https://www.turbosquid.com/3d-models/3d-oil-gas-wellhead-model-2045481 — or pumpjack look: https://www.cgtrader.com/3d-models/industrial/machine/oil-field-pump-jack |
| **SEP** separator + **HTR** line heater (horizontal vessels) | ⭐ exports **GLTF**: https://www.cgtrader.com/3d-models/industrial/industrial-machine/oil-field-separator-pbr-textures-cinematic-realistic-aaa-asset · free: https://www.cgtrader.com/free-3d-models/industrial/other/separator-oil-and-gas |
| **CMP** gas-lift compressor skid | https://www.cgtrader.com/3d-models/compressor · https://www.cgtrader.com/3d-models/industrial/industrial-part/pump-skid |
| **OT1/OT2/PWT** tank battery | https://www.cgtrader.com/3d-models/oil-tank · https://www.cgtrader.com/3d-models/industrial/other/petroleum-refinery-storage-tanks |
| **FLR** flare stack | in the Oil-tanks+flare model above |
| **EFM** custody meter / piping / manifolds | https://www.turbosquid.com/3d-models/3d-oil-natural-gas-pipelines-1162938 |
| **RTU / PWR / SOL / COM / TWR** | don't buy — grab CC0 free from Sketchfab / Kenney / Quaternius (see above) |

### ⚠️ 4 rules before you buy
1. **License:** confirm **Royalty-Free** (TurboSquid) / **Royalty-Free License** (CGTrader). **Avoid "Editorial Use Only."**
2. **Format:** prefer **glTF/GLB**; FBX/OBJ fine (Blender → export `.glb`). The CGTrader separator offers GLTF directly.
3. **Poly count:** filter **low-poly / game-ready / VR**; run heavy models through `gltf-transform`/Draco or the browser twin will choke.
4. **Match the gear:** horizontal vessels for SEP/HTR, vertical cylinders for tanks, recip/screw skid for CMP, Christmas-tree (not pumpjack) for a *gas* well.

**Recommended buy:** one refinery/vessel collection + the CGTrader separator (GLTF) + a wellhead + a compressor skid (~$100–200 total); leave the utility assets as free CC0.
