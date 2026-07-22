# P3 Backend API Contract — remaining moats (Restyle Spec v1.0 §10)

**From:** dashboard lane · **To:** backend lane
**Rule:** every field below is ADDITIVE and OPTIONAL. The dashboard module
(`aevus-hphmi.js`) renders gracefully when a field is absent, and lights the
corresponding feature up the moment it appears. Ship in any order.

Related handoffs already in docs/: `HANDOFF_PEARL_BAND_UNIFICATION.md`
(pearl 60/30 → 80/50 anchor remap), `SEC_API_KEY_ROTATION.md` (done except
the WS demo-token follow-up).

---

## 1. Fade margin — the honest radio metric (Boyer R6-1)
**Endpoint:** `GET /api/v1/assets` (radio-type assets' vitals)
```json
{ "label": "FADE MARGIN", "raw_value": 36.2, "unit": "dB", "status": "good",
  "basis": { "rssi_dbm": -67.7, "sensitivity_dbm": -108.0, "rate": "9600" } }
```
- Compute: RSSI − receiver sensitivity at configured over-air rate (JR900 ≈ −108 dBm).
- Band edges (threshold registry): ≥30 good · 20–30 warn · <20 bad.
- Frontend: renders as a BandBar automatically (vitals pipeline); the
  "signal quality %" abstraction gets retired when this ships.

## 2. Poll-cycle evidence — stale causes (Boyer R6-2/3)
**Endpoint:** `GET /api/v1/assets` (per asset, top level)
```json
{ "poll": { "interval_s": 30, "success_pct_1h": 98.7,
            "consecutive_misses": 0, "last_good": "2026-07-22T16:41:03Z" } }
```
- Frontend: stale chips gain the cause ("3 consecutive poll timeouts, last
  good 16:41") instead of wall-clock-only inference; feeds the trust states.

## 3. Per-link integrity state — up ≠ trustworthy (D'Amico R4-2)
**Endpoint:** `GET /api/v1/pearls/grid` (per pearl)
```json
{ "pearl_id": "subscriber_radio", "score": 92, "status": "good",
  "integrity": "expected" }
```
- Enum: `expected` · `new_talker` · `protocol_deviation` · `config_change` · `unknown`.
- Source: SNMP talker baselines / Modbus exception rates / dnp3 IIN — start
  with a learned (asset, protocol, peer) tuple baseline; `unknown` is honest.
- Frontend: violet dotted ring on the pearl, distinct from health fill —
  healthy-but-suspect is the earliest attack cue.

## 4. Adversary as third cause class (D'Amico R4-1)
**Endpoint:** `GET /api/v1/correlations` (per IL9000 finding)
```json
{ "attribution": { "environment": 0.82, "equipment": 0.14,
                   "adversary_plausible": 0.04 },
  "confidence": 0.82, "expires": "2026-07-22T18:00:00Z",
  "evidence": { "r": -0.82, "n": 288, "window_h": 24 } }
```
- Frontend: Watch Item cause bars become three-way; `adversary_plausible`
  > 0.25 adds a "Verify locally" action + capture-and-escalate button.
- Confidence + expiry drive the decay/auto-release semantics (Woods).

## 5. Ghost pearls — forecast comm health (Endsley R1-A + Boyer R6-A)
**Endpoint:** `GET /api/v1/pearls/grid`
```json
{ "forecast": [ { "horizon_h": 1, "pearls": [ { "pearl_id": "subscriber_radio",
    "score": 84, "basis": "fade-margin vs wind regression, gusts 22 forecast" } ] },
  { "horizon_h": 4, "pearls": [ ... ] } ] }
```
- Source: per-path RSSI-vs-wind regression × NWS forecast already cached.
- Frontend: renders ghost rows at 40% opacity, dashed, labeled FORECAST.

## 6. Cross-domain first-out (Hollifield R3-N1)
**Endpoint:** `GET /api/v1/alerts` (per alert)
```json
{ "first_out": true, "domain": "rf" }
{ "consequence_of": "AL-1402", "attribution_confidence": 0.81 }
```
- Rules (Woods guardrails, non-negotiable): consequential demotion only at
  confidence ≥ 0.85; P1/critical never demoted; the causal claim ships with
  the alert so the row can display and reverse it.
- Frontend: `⊣FIRST OUT · RF` badge; consequentials at 70% opacity with
  one-tap un-demote.

## 7. Demo WS token (SEC follow-up)
`GET /` server-side template injects `window.AEVUS_WS_TOKEN` (short-lived,
scoped read-only) when serving the demo; `/api/v1/ws?token=` accepts it.
Restores real-time push for demo sessions (currently REST-polling only —
WS handshakes carry no Referer).

## 8. Site DVR (phase B — larger)
Event-sourced state store: append-only `GET /api/v1/events?from=&to=`
returning typed events (telemetry deltas, alarms, acks, declarations,
escalations). The frontend scrubber, replay, and Marey timeline build on
this. Design session recommended before implementation.

---
**Sequencing suggestion:** 1–2 are small and immediately upgrade honesty;
3–4 are the cyber story; 5–6 are the demo showstoppers; 7 restores push;
8 is its own project. Items 1–6 are pure API additions — no schema breaks.
