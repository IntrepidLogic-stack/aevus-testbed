# Phase 2 — Read-API Convergence (design)

Part of the edge→cloud convergence
(`docs/ARCHITECTURE_edge_to_cloud_convergence_v1.md` §5, Phase 2).
**Status:** design — implement only after Phase 1 (PR #36) is applied and
telemetry is verified flowing into `aevus-latest-state`.

## Goal

Make the cloud read-API (`GET /api/v1/assets`, `/assets/{id}`) serve current
values from the **stream-backed latest-state store** (DynamoDB, Phase 1) instead
of the EC2-local SQLite that's populated by cloud-side OT polling + the
`aevus_bridge_v2.py` SQLite copier. This removes the need for the cloud to poll
OT (Phase 3) and to run the bridge (Phase 4).

## The data-ownership split (important)

An `Asset` in the API response has three kinds of fields. They do NOT all come
from the same place, and Phase 1 only covers the second:

| Field group | Examples | Source of truth |
|---|---|---|
| **Registry / metadata** | id, type, name, vendor, model, location, lat/long | Asset registry (today: SQLite `assets`; target: a registry table / SiteWise asset model) |
| **Live telemetry** | RSSI, temp, voltage, signal quality, packets | **DynamoDB latest-state** (Phase 1) ✅ |
| **Derived / state** | health, status, firmware, last_seen, uptime%, events, active alarms | Computed/edge-published **state** — NOT yet captured by Phase 1 |

**Finding:** Phase 1's rule captures only `…/telemetry/…`. For the read-API to
fully source from the stream we must also capture the edge's **state** topics
(`…/state/…`) and a periodic **health/status** publish. Call this **Phase 1.5**
(below). Until then, Phase 2 runs as a *merge*: registry+state from SQLite,
live vitals from DynamoDB.

## Phase 1.5 — capture state northbound (prereq for full cutover)

The edge already has `publish_state()` (`mqtt_publisher.py`) and publishes to
`aevus/{site}/{asset}/state/{key}`. Add:

1. **Edge:** publish `firmware`, `health`, `status`, `last_seen`, `uptime_24h`
   as state keys each poll cycle (scheduler already computes all of these).
2. **IoT rule** `aevus_state_to_ddb`: `SELECT … FROM 'aevus/+/+/state/+'` →
   same `aevus-latest-state` table, `metric = state:{key}` (namespaced so state
   and telemetry coexist under one PK without collision).

Then a single `Query(asset_id)` returns telemetry **and** state for the asset.

## Phase 2 implementation (safe, feature-flagged, dual-read)

### 2a. `DynamoLatestStateReader` (new module)

`src/storage/dynamo_latest_state.py`:
- `get_asset_vitals(asset_id) -> list[VitalSign]` — `Query` PK=asset_id, map
  telemetry items → VitalSign; map `state:*` items → firmware/health/status.
- `list_asset_ids() -> list[str]` — from the registry, not a Dynamo scan
  (registry stays authoritative for "what assets exist").
- boto3 client; region + table from settings; structured-log + empty-fallback
  on any error (never raise into the request path).

### 2b. Merge in the assets API, behind a flag

`src/config.py`: `read_source: Literal["sqlite","dynamo","dual"] = "sqlite"`
(default unchanged → zero production impact until flipped).

`src/api/assets.py`:
- `sqlite` → today's behavior (unchanged).
- `dynamo` → registry metadata from SQLite + vitals/state from Dynamo.
- `dual` → read both, return Dynamo, **log per-field diffs** vs SQLite. This is
  the validation mode: run it for a day, confirm parity, then flip to `dynamo`.

### 2c. Cutover sequence

1. Apply Phase 1 (+1.5). Verify `aws dynamodb scan` shows RAD-01/02 + others.
2. Deploy backend with `read_source=dual` on a **non-prod** read first if
   possible; inspect diff logs for parity (units, rounding, freshness).
3. Flip `read_source=dynamo` on EC2 (env var; no code change). Dashboard
   contract is identical — no frontend change.
4. Soak. If anything looks off, set `read_source=sqlite` (instant rollback, no
   redeploy).

### 2d. Rollback

`read_source` is a single env var. `sqlite` restores the exact current behavior
with no redeploy. The SQLite path is left fully intact through Phase 2–3 and
only removed in Phase 4 after Dynamo is proven.

## Explicit non-goals for Phase 2

- Do **not** remove EC2 OT polling yet (that's Phase 3 — only after Dynamo is
  the proven read source).
- Do **not** delete the bridge yet (Phase 4).
- Do **not** change the dashboard JSON contract — the whole point is the
  frontend doesn't notice.

## Acceptance criteria

- [ ] `read_source=dual` logs <0.1% field divergence over 24h vs SQLite.
- [ ] With `read_source=dynamo`, `/api/v1/assets` returns RAD-01 with real
      firmware + live vitals sourced entirely from DynamoDB.
- [ ] Setting `read_source=sqlite` instantly reverts with no redeploy.
- [ ] Dynamo read errors degrade to empty vitals + logged warning, never a 500.
