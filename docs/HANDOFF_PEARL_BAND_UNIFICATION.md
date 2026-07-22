# Handoff — Pearl Band Unification (P0-6 backend half)

**From:** dashboard restyle session (feat/p0-dashboard-batch2)
**To:** backend session (M-series work)
**Blocked on:** backend lane being free — do not apply while other src/ work is in flight.

## Context
Aevus HMI Restyle Spec v1.0 directive: one shared band scale across every surface
(Endsley D10 / consensus item 7). Today there are three:

| Surface | Edges | Where |
|---|---|---|
| Health scores (backend truth) | 80 / 50 | `src/engine/health_score.py`, CLAUDE.md |
| Pearls | 60 / 30 | `src/engine/pearl_score.py:74` (`band(score, warn_at=60, crit_at=30)`) |
| Health page legend (frontend) | ~~90 / 70~~ | FIXED — now 80/50 (batch 2, api-client.js) |

The dashboard batch-2 commit unified all frontend health displays to 80/50.
Pearls remain 60/30 — internally consistent (backend + Telecom legend agree),
but a pearl at 62 and a health score at 62 now render different bands. One
scale should win.

## Proposed change (backend)
`src/engine/pearl_score.py` maps physical thresholds to score-space anchors
with 60 = warn boundary by construction (e.g. `(-85.0, 60.0)` RSSI warn,
`(11.5, 60.0)` Trio low-volt, `(12.0, 60.0)` SCADAPack low-batt, 30 = crit).
To unify with health's 80/50:

1. Remap every anchor's score component: 60 → 80, 30 → 50 (piecewise-linear
   segments between anchors keep their physical x-values; only the y/score
   values move). Anchors at other scores (e.g. `(60.0, 70.0)` ISA-101 warn
   boundary) rescale proportionally within their segment:
   score' = 50 + (score − 30) × (80−50)/(60−30) for the 30–60 segment;
   score' = 80 + (score − 60) × (100−80)/(100−60) for the 60–100 segment.
2. `_band` call becomes `band(score, warn_at=80, crit_at=50)`.
3. Update the module docstring table (`60–99 good` → `80–100 good`).
4. Frontend legend (my lane, will follow): Telecom legend
   "Healthy 60–100 / Degraded 30–59 / Critical 0–29" →
   "Healthy 80–100 / Degraded 50–79 / Critical 0–49" in
   `dashboard/Aevus_Console.html` (~line 5579) — ping the dashboard session
   or grep `Healthy 60` when the backend lands.
5. Tests: `tests/` has pearl banding tests keyed to 60/30 — update boundary
   fixtures accordingly.

## Why not done in the dashboard session
Physical→score anchors are engine code in `src/` — actively-held backend lane,
and the H2 threshold-registry refactor is the right home for the edges.
