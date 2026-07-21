# Aevus Testbed — Architecture & Code Review

**Date:** 2026-07-21 · **Scope:** `testbed-kit/src` (15.1K LOC, 78 modules), `dashboard/` (8.1K-line SPA), CI/deploy · **Reviewer perspective:** senior engineer, correctness/perf/maintainability, functionality-preserving.

---

## 1. Architecture summary

Aevus is a **two-plane industrial-monitoring platform** with one shared FastAPI codebase deployed to two roles:

- **Edge plane (Raspberry Pi, on the OT LAN):** runs the collectors. Polls field gear over SNMP / Modbus TCP / DNP3 / OPC UA, normalizes readings, and republishes them north over **MQTT → AWS IoT Core**. This is the only plane that touches OT.
- **Cloud plane (EC2, `aevus.intrepidlogic.io`):** serves the dashboard + read API. Field gear is unreachable from here, so cloud assets render from the **DynamoDB latest-state** overlay fed by the edge. Collectors fall back to simulators.

The same `src/` runs in both roles; **environment flags** (`modbus_enabled`, `opcua_enabled`, `snmp_trap_enabled`, `read_source`, …) decide what activates where.

### Data flow (ingest → serve)

```
                 ┌─────────────── EDGE (Pi) ───────────────┐
 field gear ──▶  Collector.safe_poll()  ──▶ RawTelemetry
 (SNMP/Modbus/                                   │
  DNP3/OPC UA)          PollScheduler._poll_cycle (1 task/asset)
                                                 │
              ┌──────────────┬───────────────────┼───────────────┬─────────────┐
              ▼              ▼                    ▼               ▼             ▼
        Influx (raw)   normalizer→VitalSign   health_score   alert_engine   MQTT→IoT Core
                              │                    │             │               │
                              └──── SQLite (registry: asset+health+alerts) ◀─────┘
                                                 │                              (IoT Rule)
                        WebSocket broadcast ◀────┤                                  ▼
                                                 ▼                          DynamoDB latest-state
                              ┌──────────── CLOUD (EC2) ────────────┐
   dashboard SPA  ◀── /api/v1/* (FastAPI routers) ── SQLite registry ── overlay ◀─┘
   (Promise.all batch refresh)   APIKeyMiddleware (global, path-prefix auth)
```

### Layers

| Layer | Modules | Role |
|---|---|---|
| **Collectors** | `base.py` + 10 protocol collectors, `simulator.py`, trap receiver | Device I/O → `RawTelemetry`. `BaseCollector.safe_poll()` wraps failure tracking + timing. |
| **Engines** | `normalizer`, `health_score`, `pearl_score`, `alert_engine`, `prediction`, `notifier`, `correlator`, `commander`, `weather`, `*_tracker` | Raw → vitals → scores → alerts → notifications. |
| **Storage** | `sqlite_db` (registry/alerts), `influx` (time-series), `dynamo_latest_state` (cloud overlay) | Persistence. |
| **Scheduler** | `scheduler.py` | One asyncio task per asset driving the poll cycle. |
| **API** | ~28 routers under `/api/v1`, `auth.py` middleware, `ws.py` | Read API + AI + digital twin + WebSocket push. |
| **Wiring** | `main.py`, `config.py`, `secrets_loader`, `il9000` | App assembly + settings + (nominal) safety interlock. |

### What's healthy
`health_score.py` and `base.py` are model citizens — pure functions / clean abstraction, no I/O, good docstrings, typed. The **edge→cloud convergence** design (MQTT + Dynamo overlay, feature-flagged) is sound and lets one codebase serve both planes. Failure isolation at the wiring level is deliberate (every `_register_*` and background loop swallows exceptions so one bad subsystem can't crash startup).

---

## 2. Identified issues

Ranked by severity. Each: **impact** · `file:line` · fix.

### 🔴 Critical

**C1 — The IL-9000 safety interlock is decorative (P-008 is enforced by convention, not code).**
`il9000_check()` (`il9000.py:42`) always raises — but it has **zero callers** on any write path (every `il9000_check` hit in the tree is a *string column name*, not a call). Meanwhile `register_writer.py:75-105` issues live `write_registers`/`write_coil` to the real SCADAPack (`HOST="172.16.1.200"`) with **no interlock import at all**, and `commander.py:78` treats `IL_9000_ENFORCED==True` as "proceed" (inverted vs the firmware rule) and only logs a status string. Today the read-only guarantee holds only because those write paths happen to be *simulated* / a *standalone script nobody imports* — **not** because the interlock stops them. `CLAUDE.md`'s "enforced by code (not policy)" is currently false. This is the flagship patented invention; it must be real.
**Fix:** a single `assert_read_only(action)` gate that **every** Modbus/coil/register write calls; a test that asserts no unguarded `write_*` exists in `src/`; move `register_writer.py` out of importable `src/` or hard-gate it to a sim host.

### 🟠 High

**H1 — Blocking I/O on the async event loop (systemic).** The scheduler poll cycle runs **synchronous** `influx.write_readings` and **all** `sqlite` + boto3-Dynamo calls inside `async _poll_cycle` (`scheduler.py:185,199,243,297`); `prediction._analyze_metric` fires one **sync** Influx query per metric per asset per cycle (`prediction.py:295`, +2 in `_analyze_battery_solar:195`); every AI endpoint calls sync `boto3 invoke_model`/`converse` inside `async def` (`ai.py`); `main.py:627` `.read_text()`s the 8.1K-line dashboard on **every** `GET /`; OPC UA does RSA-2048 keygen inline on first connect (`opcua_security.py:79`). Any one slow call stalls **all** poll loops, the WS broadcast, and the API. **Fix:** wrap blocking I/O in `run_in_executor`/`asyncio.to_thread` (or async clients); cache the dashboard; batch prediction queries.

**H2 — Threshold definitions triplicated + two divergent scoring systems.** Warn/crit limits for the same metrics are hand-copied across `normalizer.THRESHOLD_MAP`, `prediction.MONITORED_METRICS` (`prediction.py:32`), and the pearl curves (`pearl_score.py:101`) — edit one, the others silently drift. Worse, **two** 0–100 scorers emit the same `good/warn/bad` vocabulary with **different band cutoffs**: `health_status` breaks at 80/50 (`health_score.py:151`), `pearl._band` at 60/30 (`pearl_score.py:68`) — the same asset is "good" to one engine and "warn" to the other. Status assignment is a third copy in `normalizer.evaluate_status:467`. **Fix:** one config-driven threshold registry feeding all engines; one shared `band()` utility.

**H3 — Auth is fail-open and over-exempted.** Empty `api_key` ⇒ the middleware **passes all `/api/` traffic unauthenticated** (`auth.py:105`) with no prod guard. `/ingest`, `/notes`, `/journal` are exemption-listed so **anonymous POSTs** can inject telemetry / write the "immutable" journal (`auth.py:90`), and the exact-path match means `PUT/DELETE /notes/{id}` *require* auth while `POST /notes` doesn't. The **demo bypass** keys off a spoofable `x-aevus-demo` header / `referer` and grants unauthenticated access to **paid `POST /ai/*`** Bedrock endpoints (`auth.py:111`) — a direct cost/DoS vector. **Fix:** fail closed when a prod signal is set (or at least warn loudly at startup); drop notes/journal from exemptions and require a shared secret on ingest; gate demo mode with a signed server-side token, never a client header, never AI writes.

**H4 — Collectors under-abstract; I/O + parsing copy-pasted 3–4×.** `_snmp_get`/`_snmp_get_sync` are duplicated across **4** files (`snmp_radio:187`, `snmp_router:401`, `snmp_switch:216`, `snmp_edge:202`); `_snmp_walk_sync` across **3**; timeticks→hours and memory-% parsing across 3–4 each; float32 decode is scattered and even inconsistent (Modbus `>f` big-endian vs DNP3 `<f` little-endian, no shared helper); `CISCO_OIDS` is defined twice with divergent keys. The abstraction stops at `poll()`. **Fix:** an `SNMPCliMixin` (or async SNMP client) on the base, plus shared `parse_timeticks`/`decode_float32` helpers.

**H5 — Per-request client construction (boto3 / JWKS).** `ai._get_client` (`ai.py:227`) and ~8 `access_requests` handlers build boto3 clients **per request**; `_validate_cognito_jwt` builds a fresh `PyJWKClient` per Bearer request (`auth.py:66`), doing a network JWKS fetch and ignoring the `_jwks_cache` above it (which is now **dead code**). **Fix:** module-level lazily-cached singletons; reuse one signing-key client.

### 🟡 Medium

- **M1 — Import-time side effects.** `main.py:23` `inject_secrets()` (boto3→AWS) and `main.py:202` `app_state = AppState()` (opens SQLite, makes dirs, builds InfluxDBClient) run at **import**, so any import — including CI's `test_imports` — hits real resources (hence the `# noqa: E402` forest). **Fix:** build state inside `lifespan`.
- **M2 — Global singleton + circular-import workaround.** `app_state` is a module global reached via `from src.main import app_state` inside **~37 handlers**. **Fix:** a FastAPI dependency `Depends(get_state)`.
- **M3 — God-files.** `ai.py` (848 LOC: model registry + 3 provider adapters + prompts + routing + finetune store + 10 endpoints) and `twin.py` (756 LOC: a 280-line topology literal + physics sim in the router). **Fix:** extract `services/bedrock.py`, `services/ai_router.py`, `services/twin_sim.py`; move topology/prompts/model-map to data/config.
- **M4 — SQLite concurrency.** One shared connection (`check_same_thread=False`, no lock, no WAL, no `busy_timeout`) plus a **second** independent connection in `commander.py:51` to the same file; reachability does INSERT+DELETE+commit every poll ⇒ "database is locked" under contention. **Fix:** WAL + `busy_timeout`, one serialized connection.
- **M5 — Flux injection.** `influx.query_trend` builds Flux by f-string with `asset_id`/`metric` interpolated, and `metric` can originate from API input (`influx.py:72`). **Fix:** validate/escape identifiers.
- **M6 — Dead correlation path.** `comm_quality_engine` is never instantiated and `correlator` isn't passed to the scheduler, so `_prediction_loop`'s `if self.correlator and self.comm_quality_engine` never fires (`scheduler.py:69`) — cross-domain correlation silently never runs.
- **M7 — Inconsistent `response_model`.** assets/alerts/ai/twin type responses; predictions/diagnostics/health/reports/pearls/notes/ingest return bare `dict`/`list[dict]` ⇒ no OpenAPI schema.
- **M8 — Placeholder maintenance score.** `_maintenance_score` (`health_score.py:86`) returns ~constant 80 and ignores firmware — yet is 15% of every health score, inflating it.
- **M9 — Collector teardown contract missing.** Cleanup is `close()` vs `aclose()` vs none across collectors; the scheduler special-cases each. **Fix:** `async def aclose()` on base (default no-op).
- **M10 — String-label coupling.** `alert_engine.ALERTABLE_METRICS` and `pearl._vital` match on display labels ("RSSI","BATTERY"); renaming a normalizer label silently breaks alerting/scoring.
- **M11 — Trap receiver orphaned tasks.** `asyncio.ensure_future(handle_trap(...))` fire-and-forget (`snmp_trap_receiver.py:442`) — refs unheld (GC risk), exceptions swallowed, unbounded spawn under flood.
- **M12 — 5 routers appear unwired.** `auth_config`, `opcua_assets`, `process_assets`, `reference_assets`, `relay_overlay` (~587 LOC) aren't in `main.py`'s registration loop — dead or wired in a non-obvious place; verify and either wire or delete.

### 🟢 Low
- **L1** `config.py:43-50` defines `dnp3_port`/`dnp3_master_addr`/`dnp3_outstation_addr` **twice** (second shadows first); insecure defaults (`influx_token="your-influx-token-here"`).
- **L2** Doc/code drift: `CLAUDE.md` says `IL_009_ENFORCED`; code is `IL_9000_ENFORCED`. The whole `CLAUDE.md` fleet/endpoint list has drifted from the actual 28-router reality.
- **L3** Dead code: `_get_cognito_jwks` (`auth.py:43`); no-op expression statements in `dnp3_master.py:159-161,225,232`.
- **L4** Hardcoded host paths (`weather.CACHE_PATH`, `access_requests.DATA_FILE = /home/ubuntu/...`); hardcoded Cognito pool id repeated ~7×.
- **L5** `reports.py` status→color ternary copy-pasted ~4×; `datetime.utcnow()` (deprecated) in `csv_io.py:69`; access-request IDs via `len(reqs)+1` (race-prone); temp unit `"C"` vs `"°C"`.
- **L6** `scheduler.stop()` cancels tasks but never awaits them.

---

## 3. Refactoring recommendations (prioritized)

1. **Make IL-9000 real (C1).** One `assert_read_only()` gate on every write call + a guard test. Highest value: it's the safety guarantee *and* the patent. Low blast radius (write paths are simulated today).
2. **Un-block the event loop (H1).** Introduce an `run_blocking()` helper (`asyncio.to_thread`) and route Influx/SQLite/boto3/Dynamo through it; cache the dashboard; batch prediction's per-metric queries into one asset query. Biggest runtime-behavior win.
3. **Single source of truth for thresholds + banding (H2).** A `engine/thresholds.py` registry (seeded from `settings`) consumed by normalizer, prediction, and pearl; one `band(score, warn, crit)` in `engine/scoring.py`. Kills three-way drift.
4. **De-dupe collectors (H4).** `SNMPCliMixin` + shared `parse_timeticks`/`decode_float32`; unify `CISCO_OIDS`. ~300 LOC removed, drift eliminated.
5. **Harden auth (H3).** Fail-closed prod guard, remove over-exemptions, signed demo token, cached JWKS/boto3 clients (H5).
6. **Wiring hygiene (M1/M2).** Move `AppState` construction into `lifespan`; expose it via `Depends(get_state)`; delete the 37 `from src.main import app_state` lines.
7. **Break up god-files (M3).** Extract Bedrock/twin services; move data literals out of routers.
8. **Storage robustness (M4/M5).** WAL + `busy_timeout` + one connection; parameterize/validate Flux identifiers.

**Sequencing:** 1, 2, 5 are safety/perf/security and should land first. 3, 4, 6, 7 are structural and can follow behind tests. Each is independently shippable behind the existing CI gate.

---

## 4. Improved code (this pass)

Behavior-preserving, verified against the full suite (429 passed). See the accompanying PR. Implemented now:

- **`config.py`** — removed the duplicate DNP3 keys (L1).
- **`main.py`** — the dashboard HTML is read **once at import** and served from memory (`FileResponse`-equivalent cache) instead of `.read_text()` per request; the deploy restarts the process, so the cache always reflects the deployed file (H1, hot path).
- **`auth.py`** — deleted dead `_get_cognito_jwks`; the Cognito signing-key client is built **once** and reused; a startup **warning** now fires when auth is fail-open (`api_key` empty) so a mis-provisioned prod box is loud, not silent (H5 + H3 visibility, no behavior change to valid auth).
- **`engine/scoring.py`** (new) — one `band(score, warn, crit)` utility; `health_score.health_status` now delegates to it (identical 80/50 behavior) as the seed of H2's shared banding.

Deferred (recommended, needs your go — safety/behavior-sensitive): the real IL-9000 gate (C1), the executor-wrapping of scheduler I/O (H1 core), the threshold registry (H2), and the collector mixin (H4). Each is scoped above and I can implement + verify on request.
