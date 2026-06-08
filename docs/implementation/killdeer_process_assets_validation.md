# Killdeer Field — Controlled Validation: `PROCESS_ASSETS_ENABLED=1`

**Date:** 2026-06-07
**Ticket:** K-T4 (reconciliation roadmap)
**Owner:** TBD per execution
**Type:** Controlled local validation procedure — **NOT a production flag flip**

---

## 1. Purpose

Execute the missing plan-step-6 validation for the flag-gated CMP overlay
landed by PR #103 (`feat(process-assets): add flagged CMP asset binding path`).

The flag `PROCESS_ASSETS_ENABLED` shipped to production **off** by default and
has not been exercised on a flag-on path beyond unit-test coverage. This
document is the controlled-validation runbook that fills that gap **without
flipping the flag in any deployed environment**.

This procedure is **local / control-box only**. It does not modify production,
staging, or CI environments. It does not change the repository default for
`PROCESS_ASSETS_ENABLED`. It does not require a production API key.

---

## 2. Current baseline

| Item | State |
|---|---|
| `main` HEAD at procedure authoring time | `13ada56` (post-K-T3) |
| CMP overlay code | Deployed flag-off (PR #103 merged in `8a501eb`, present on `main`) |
| `settings.process_assets_enabled` | Defaults to `False` in [`src/config.py`](../../src/config.py) |
| `/api/v1/assets` flag-off behavior | Byte-identical to pre-PR #103 (guaranteed by the early return in [`src/api/process_assets.py`](../../src/api/process_assets.py) `if not settings.process_assets_enabled` and unit-tested in `tests/test_process_assets.py::test_disabled_returns_empty`) |
| Production authenticated smoke for `/assets` / `/twin/.../process` | **BLOCKED** — no safe API key has been sourced in any working session to date. See `docs/implementation/pr104_post_merge_deployment_note.md` §8. |

**This procedure does not replace production authenticated smoke testing.** It
exercises the flag-on path on a local control box only. Production readiness
of a future flag flip remains a separate ticket and is explicitly out of scope.

---

## 3. Preconditions

1. Branch off current `origin/main` in a working copy of `testbed-kit/`.
2. Python 3.11+ with the project's dev dependencies installed
   (`pip install -e .[dev]` or equivalent).
3. The unit-test suite passes on a clean `main` (`pytest -q` reports
   373 / 373 pass at `13ada56`).
4. For the hermetic (TestClient) path: no `.env` is required; the test
   fixture pattern already used in `tests/test_twin.py` patches
   `src.api.auth.settings.api_key = ""` to disable the `X-API-Key`
   middleware for the duration of the test.
5. For the optional uvicorn / curl path: a local `.env` with the minimum
   non-prod values (SQLite path local, InfluxDB token may be empty if the
   storage layer tolerates it; auth is left disabled with
   `API_KEY=""` for the validation window only).

**No production API key is required.** No production secret should be sourced
for this procedure. If at any step a production-credentialed call is needed,
**stop** and treat it as a separate, gated activity.

---

## 4. Hermetic TestClient validation path (PREFERRED)

The hermetic path is deterministic, dependency-light, and runnable anywhere
`pytest` runs (including the existing CI job). It does not require a
running uvicorn server or a populated SQLite file.

### 4a. Steps

1. Check out a working copy at the current `origin/main` HEAD.
2. From the repo root, run the existing process-asset overlay tests:
   ```bash
   pytest -q tests/test_process_assets.py
   ```
   Expect: all tests pass.
3. Run the suite-wide tests to confirm baseline:
   ```bash
   pytest -q
   ```
   Expect: 373 / 373 pass (or current baseline at the time of validation).
4. From a Python REPL or scratch script (no source-code edits), exercise
   the overlay with the flag mocked **on**:
   ```python
   from unittest.mock import MagicMock, patch
   from src.api import process_assets as pa
   from src.models.asset import Asset
   from src.models.telemetry import VitalSign
   from datetime import UTC, datetime

   def _v(label, status, val=1.0, unit=""):
       return VitalSign(label=label, value=f"{val}{unit}", raw_value=val,
                        unit=unit, status=status)

   rtu = Asset(id="RTU-01", type="rtu", status="good",
               name="SCADAPack 470", location="lab", health=90,
               last_seen=datetime.now(UTC),
               vendor="Schneider", model="SCADAPack 470",
               protocol="modbus",
               vitals=[
                   _v("SUCTION PRESSURE", "good", 245.0, "PSI"),
                   _v("DISCHARGE PRESSURE", "good", 1180.0, "PSI"),
                   _v("VIBRATION", "good", 2.1, "mm/s"),
                   _v("RSSI", "good", -68.0, "dBm"),  # non-compressor, excluded
               ])

   state = MagicMock()
   state.db.get_asset.return_value = rtu
   with patch.object(pa, "settings", MagicMock(process_assets_enabled=True)), \
        patch("src.main.app_state", state):
       result = pa.process_assets()

   assert len(result) == 1
   assert result[0].id == "CMP"
   assert result[0].status == "good"
   ```
5. Toggle the flag off in the same script and confirm `[]`:
   ```python
   with patch.object(pa, "settings", MagicMock(process_assets_enabled=False)):
       assert pa.process_assets() == []
   ```
6. Exercise the API surface (no uvicorn needed) by mounting a `TestClient`
   over the same flag-on patch and reading `/api/v1/assets`:
   ```python
   from fastapi.testclient import TestClient
   from src.main import app
   with patch("src.api.auth.settings") as auth_s, \
        patch.object(pa, "settings", MagicMock(process_assets_enabled=True)), \
        patch("src.main.app_state", state):
       auth_s.api_key = ""
       auth_s.api_key_header = "X-API-Key"
       with TestClient(app) as c:
           r = c.get("/api/v1/assets")
           assert r.status_code == 200
           ids = {a["id"] for a in r.json()}
           assert "CMP" in ids
   ```

### 4b. What the hermetic path proves

- The overlay function returns a `CMP` asset when the flag is on and a
  compressor-vital-bearing RTU is present.
- The overlay returns `[]` when the flag is off.
- `/api/v1/assets` includes the `CMP` row when the flag is on, with no
  source-code change to `src/api/assets.py` or `src/api/process_assets.py`.
- The endpoint's behavior with the flag **off** is byte-identical to
  pre-PR #103 (covered by the existing `test_disabled_returns_empty`).

### 4c. What the hermetic path does NOT prove

- It does not verify behavior against a real SCADAPack 470 or a live
  Modbus poll.
- It does not verify dashboard rendering of the CMP card (Section 8).
- It does not verify production behavior under the production
  auth/secrets pipeline (Section 10).

---

## 5. Optional local uvicorn / curl validation path

A secondary, human-facing procedure for operator confidence. Useful when the
implementer wants to see the CMP asset appear via a real HTTP round-trip.
**Local only.** Never run this against staging or production.

### 5a. Steps

1. From a clean working copy of `origin/main` (or this PR's branch), in a
   throwaway shell:
   ```bash
   export PROCESS_ASSETS_ENABLED=1
   export API_KEY=""               # local validation only — disables auth
   uvicorn src.main:app --port 18000 --reload
   ```
   The port `18000` is arbitrary; use any free port other than the project
   default to avoid colliding with other local services.

2. In a second shell:
   ```bash
   curl -s http://127.0.0.1:18000/api/v1/health/ping | jq .
   # Expect: {"status":"ok","service":"aevus","version":"..."}

   curl -s http://127.0.0.1:18000/api/v1/assets | jq '[.[] | .id]'
   # Expect: includes "CMP" alongside the local seeded asset IDs.

   curl -s http://127.0.0.1:18000/api/v1/assets/CMP | jq '{id,type,status,health,vitals:[.vitals[].label]}'
   # Expect: id=="CMP", vitals are a subset of the SCADAPack 470 compressor
   # register labels (SUCTION PRESSURE, DISCHARGE PRESSURE, GAS TEMP,
   # VIBRATION, MOTOR CURRENT, COMPRESSOR RPM, INTERSTAGE TEMP, OIL PRESSURE,
   # COOLANT TEMP, RUN HOURS).

   curl -s -o /dev/null -w "%{http_code}\n" \
       http://127.0.0.1:18000/api/v1/twin/facility/killdeer/process
   # Expect: 200

   curl -s -o /dev/null -w "%{http_code}\n" \
       http://127.0.0.1:18000/api/v1/twin/facility/nope/process
   # Expect: 404
   ```

3. Rollback rehearsal:
   ```bash
   # In the uvicorn shell:
   #   Ctrl-C
   unset PROCESS_ASSETS_ENABLED
   uvicorn src.main:app --port 18000

   # In the second shell:
   curl -s http://127.0.0.1:18000/api/v1/assets | jq '[.[] | .id] | contains(["CMP"])'
   # Expect: false (CMP gone)
   ```

### 5b. Notes

- The `API_KEY=""` line above disables the `X-API-Key` middleware for the
  validation window only. Do not commit this value. Do not export it in any
  shared shell, CI runner, or `.env` that gets sourced by anything other
  than the validating operator.
- The local uvicorn process should be killed at the end of validation; do
  not leave it running on a control box that other users access.
- The local SQLite file used during this validation is disposable; if the
  control box has a "real" SQLite seed in use, run validation in a
  throwaway directory (or against a separate `SQLITE_PATH`).

---

## 6. Required probes / assertions

The matrix below is the contract for what a successful K-T4 run looks like.
All assertions must pass before the validation is considered complete.

| # | Probe | Flag | Expected | Why it matters |
|---|---|---|---|---|
| P1 | `GET /api/v1/assets` | `PROCESS_ASSETS_ENABLED` **unset / false** | 200; response list does **not** include `CMP`; the local seeded assets are present | The flag-off byte-identical guarantee for `/assets` (the safety contract behind PR #103's flag-off deploy). |
| P2 | `GET /api/v1/assets` | `PROCESS_ASSETS_ENABLED=1` | 200; response list **includes** `CMP` alongside the local seeded assets | The flag-on overlay path actually surfaces the derived asset. |
| P3 | `GET /api/v1/assets/CMP` | `PROCESS_ASSETS_ENABLED=1` | 200; `id == "CMP"`; vitals are a strict subset of the SCADAPack 470 compressor register labels | The asset is fully resolvable by id and carries only the compressor-group vitals (no RSSI / non-compressor labels leak through). |
| P4 | CMP vitals lineage | `PROCESS_ASSETS_ENABLED=1` | CMP `vitals[*].label` ⊆ `{"SUCTION PRESSURE", "DISCHARGE PRESSURE", "GAS TEMP", "VIBRATION", "MOTOR CURRENT", "COMPRESSOR RPM", "INTERSTAGE TEMP", "OIL PRESSURE", "COOLANT TEMP", "RUN HOURS"}` | Confirms the binding contract (CMP is built from RTU-01's compressor-group registers, not raw process model). |
| P5 | `GET /api/v1/twin/facility/killdeer/process` | either | 200; body is a `ProcessSnapshot` with non-empty `stages` | Confirms the demo-gated process snapshot still serves and is not affected by the flag. |
| P6 | `GET /api/v1/twin/facility/nope/process` | either | 404 | Confirms the `_DEMO_FACILITIES` allowlist from PR #103 is still in effect (no simulated leak on non-demo facilities). |
| P7 | Rollback: `unset PROCESS_ASSETS_ENABLED` then restart, repeat P1 | flag **off** after having been on | `/assets` response equals the P1 result; `CMP` is gone | Confirms instantaneous rollback (no seed/migration/cache state to clean up). |

Optional dashboard observation (Section 8) is qualitative and does not
gate the validation.

---

## 7. Expected evidence template

Copy this block into the validation PR description (and / or paste into
this file under a dated `## Validation runs` heading) when running the
procedure. Do **not** commit screenshots into the repo; link them or
attach to the PR.

```
## Validation run — <ISO date>

- Validator: <name>
- Commit (HEAD of feat/* branch under test): <git rev-parse --short HEAD>
- main HEAD at run time: <git rev-parse --short origin/main>
- Environment: <local hostname / control box>
- Python: <python --version>
- pytest baseline: <NN/NN pass on origin/main>
- Path used: [hermetic | uvicorn-curl | both]

### Results

| # | Probe | Result | Notes |
|---|---|---|---|
| P1 | /assets flag-off | PASS / FAIL | ids: [...] |
| P2 | /assets flag-on  | PASS / FAIL | ids: [..., CMP] |
| P3 | /assets/CMP      | PASS / FAIL | status=<>, health=<> |
| P4 | CMP vitals lineage | PASS / FAIL | labels: [...] |
| P5 | /twin/killdeer/process | PASS / FAIL | stages=<n> |
| P6 | /twin/nope/process     | PASS / FAIL | status=<> |
| P7 | rollback /assets       | PASS / FAIL | ids match P1: yes / no |

### Anomalies / notes

- <any deviations, unexpected statuses, warnings, etc.>
- <links to screenshots if dashboard was observed>
```

---

## 8. Dashboard observation guidance

Local only. Open the dashboard at the local uvicorn root (`http://127.0.0.1:18000/`)
while `PROCESS_ASSETS_ENABLED=1`. Visit:

- **Overview** — confirm the new modeled-reference banner from K-T3 is
  visible; confirm that the page renders without errors.
- **Map** — confirm the procedural 3D twin still loads (the topology
  endpoint is unchanged; the CMP asset addition does not modify
  `/api/v1/twin/facility/killdeer/topology`).
- **Assets list** (if linked from the topbar / sidebar) — visually
  confirm a `CMP` row exists alongside the lab fleet (`RTU-01`,
  `RAD-01`, …). The CMP card should show its derived vitals.

Capture screenshots **outside the repo** (e.g. in the validator's notes,
attached to the PR description). **Do not commit screenshots** to the
repo. The dashboard observation is qualitative confirmation; the
hermetic / curl probes in Section 6 are the source-of-truth assertions.

---

## 9. Rollback

The flag-off rollback is instantaneous and stateless:

1. `unset PROCESS_ASSETS_ENABLED` in the running shell.
2. Restart the local uvicorn process (`Ctrl-C` and re-launch).
3. Re-run P1 / P7: `curl -s http://127.0.0.1:18000/api/v1/assets | jq '[.[] | .id]'`
   — verify `CMP` is absent.
4. Verify the local-seeded asset rows (`RTU-01`, `RAD-01`, …) are still
   present and unchanged.

No data fix-up is required. The overlay never touches the SQLite registry,
never writes to InfluxDB, and never raises into `/assets` (the overlay's
internal exception swallow path is the existing
`tests/test_process_assets.py::test_never_raises_on_error` contract).

---

## 10. Known limitations

- **Production validation is out of scope.** This procedure does not
  prove the flag works in production. Production validation requires an
  approved API key (see `pr104_post_merge_deployment_note.md` §8). That
  remains a separate, future ticket. **Do not flip
  `PROCESS_ASSETS_ENABLED` in production based on this procedure alone.**
- **Real SCADAPack hardware is not exercised.** Vitals used by the
  hermetic path are simulated `VitalSign` objects; vitals seen via the
  uvicorn / curl path come from whatever the local SQLite registry
  contains for `RTU-01` (typically the simulator, per
  `src/collectors/simulator.py`). Real Modbus polling behavior is not
  tested here.
- **Per-process-node asset rows are NOT introduced.** Audit finding A-1
  (the request to grow `Asset.type` past lab hardware types to include
  process types like separator/compressor/heater) is explicitly
  deferred. This procedure validates only the single derived `CMP`
  overlay row.
- **`_TOPOLOGY.origin` geography drift (audit finding K-1) is unaffected**
  and not part of this validation. The topology Texas/ND question
  remains open.
- **The dashboard's `aevus-killdeer-3d.js` offline fallback (K-T1)** is
  not exercised by this procedure (the live `/topology` endpoint
  responds; the fallback path only fires when the API is unreachable).
- **No CI test gate is added for the dashboard CMP card.** The dashboard
  observation in Section 8 is operator-screenshot evidence only;
  introducing a UI test would expand scope and is deferred.

---

## 11. Validation runs

_Append per-run blocks (see template in §7) below this line._
