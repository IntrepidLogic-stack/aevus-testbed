# UXDA Award Submission Build — RECOVERED (2026-06-03)

These are the **May 27 2026 "awards-polish" dashboard build** — the version Aevus
was judged on and **nominated** for the UX Design Award. It was never committed to
`dashboard/` on main; it lived only on the production EC2 and was overwritten on the
served files by later deploys (deploy.sh blind-checkouts dashboard/ from git).

Recovered from EC2 `i-017562fca3e3401a8:/home/ubuntu/aevus-testbed/dashboard/` via SSM + web pull.

| File | What it is |
|---|---|
| `award-Aevus_Console.html` | The award HTML (loads `api-client.js`) — stylized "Monitor" SCADA facility map, full layer sections (SCADA Layers / Intelligence / Map Style), legend. |
| `award-api-client.min.js` | The award JS, minified — what was served as `api-client.js` on May 27. |
| `award-api-client.src.js` | **Readable source** (19,008 lines) of the award build — the map module to port forward. |

## Why this matters
The **current feature-rich build** (Telecom/Rickerson pearls, radio comms rebuild,
historian, SCADAPack front-end — all May 28-31) has the NEW features but a simpler
street-map. The award build has the RICH map but none of the new features.

**The goal: merge the award MAP module from here into the current feature build**, so
the live platform (and the nominee video) shows the award-quality map + all upgrades.

Award-map fingerprints (absent from the current build): `LACT Unit`, `EFR Skid`,
`Health Gradient`, `Alarm Heat Map`, `Dispatch Route`, `Anomaly Map`, `MONITOR/SATELLITE/HYBRID`.
