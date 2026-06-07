# PR #104 — Post-merge Deployment Note

**Date:** 2026-06-07
**Type:** Deployment record (docs only — no code, no flag change, no env change)

---

## 1. PR

- **Number:** [#104](https://github.com/IntrepidLogic-stack/aevus-testbed/pull/104)
- **Title:** `docs(killdeer): add current state reconciliation audit`
- **Base branch:** `main`
- **Head branch:** `docs/killdeer-current-state-reconciliation`
- **Final state:** MERGED · `mergedAt: 2026-06-07T15:53:40Z` · `mergedBy: IntrepidLogic-stack`

## 2. Main merge commit

**`ffee86d`** — `Merge pull request #104 from IntrepidLogic-stack/docs/killdeer-current-state-reconciliation`

## 3. Included commits

| SHA | Message |
|---|---|
| `ca3b02b` | `docs(killdeer): add current state reconciliation audit` (the program-control reconciliation doc) |
| `db010e8` | `fix(killdeer): align fallback and spline contracts to 25-node topology` (K-T1; rebased equivalent of the original `5d0573e` — identical tree hash `9ccd8495…`) |

The reconciliation doc landed first; the K-T1 fix was stacked on top via PR #105 (merged into the docs branch with `--rebase`) and arrived in `main` as part of the PR #104 merge.

## 4. Files changed in the merge

| File | Change | +/- |
|---|---|---|
| `docs/implementation/killdeer_current_state_and_reconciliation.md` | ADDED | +285 / −0 |
| `dashboard/aevus-killdeer-3d.js` | MODIFIED | +58 / −26 |
| `dashboard/aevus-spline-twin.js` | MODIFIED | +9 / −1 |
| `docs/SPLINE_TWIN_AUTHORING_CONTRACT.md` | MODIFIED | +35 / −18 |

Four files. No others. Verified by `git diff --name-only 8a501eb..ffee86d`.

## 5. CI/CD result

**SUCCESS** — workflow run `27097404228` against `ffee86d`, completed in ~10m57s.

| Job | Result |
|---|---|
| `Lint & Format Check` | success |
| `Security Scan` | success |
| `Test Suite` | success (373/373) |
| `All Checks Passed` | success |
| `Deploy to EC2` | success |

## 6. Deploy result

**SUCCESS** — `Deploy to EC2` job (`ci.yml` job `deploy`, gated `if: github.ref == 'refs/heads/main' && github.event_name == 'push'`) fired on the merge push and POSTed to `https://aevus.intrepidlogic.io/api/v1/deploy/trigger`. The webhook returned 0 (curl `-sf`); the box-side `deploy/deploy.sh` (under the `aevus-deploy` flock + `concurrency` group) completed and rolled the new bundle into the served path.

## 7. Evidence that the deploy landed

Non-authenticated probes against `https://aevus.intrepidlogic.io`:

| Probe | Result |
|---|---|
| `HEAD /dashboard/aevus-killdeer-3d.js` | HTTP 200 · `last-modified: Sun, 07 Jun 2026 16:04:35 GMT` (matches end of CI/CD run) · `Content-Length: 192942` |
| `GET /dashboard/aevus-killdeer-3d.js \| grep aevus_twin_topo_v` | `aevus_twin_topo_v19` present — confirms the `v18 → v19` cache-key bump from `db010e8` is what's serving |
| `GET /` (dashboard root) | HTTP 200 · `<title>Aevus — Killdeer Field</title>` |
| `GET /api/v1/health/ping` (public liveness) | HTTP 200 · `{"status":"ok","service":"aevus","version":"0.1.0"}` |

The FastAPI app is up; the dashboard SPA is served; the JS bundle that was modified by PR #104 is the version on disk on the box.

## 8. Authenticated smoke test status

**BLOCKED — not run.**

- Endpoints that require `X-API-Key`: `/api/v1/health/summary`, `/api/v1/assets`, `/api/v1/twin/facility/{id}/process`.
- All four return HTTP 401 (`Invalid or missing credentials`) when probed without a key — that is correct middleware behavior, not a deploy regression.
- No safe API key source was available in this session: shell environment was empty (`AEVUS_API_KEY`, `API_KEY`, `X_API_KEY`, `AEVUS_X_API_KEY`, `AEVUS_KEY` all unset); local `.env` does not contain an `API_KEY`; production `api_key` lives in AWS Secrets Manager (per `src/secrets_loader.py` and the CLAUDE.md note) and was not pulled.
- **Do not paste secrets into chat.** If completion of the auth-gated smoke tests is needed, source the key from the approved local/ops procedure and run the four curls directly — do not exfiltrate the value into the conversation.
- Therefore the following four expectations from the PR #104 post-merge plan **remain unverified at the 200-level**:
  1. `/api/v1/health/summary` → 200 with summary body
  2. `/api/v1/assets` → 200, response list omits `CMP`, existing 7-row lab fleet present
  3. `/api/v1/twin/facility/killdeer/process` → 200 with stages payload
  4. `/api/v1/twin/facility/nope/process` → 404 (the `_DEMO_FACILITIES` gate from PR #103)

The behavior is **strongly expected** to be correct (no code changed in the affected paths since 8a501eb, the `Test Suite` job exercises every one of these endpoints, the deploy was a static-bundle swap), but the live 200-level check is the missing piece.

## 9. Risk posture

- **No backend code changed** in this merge. `src/api/twin.py`, `src/api/assets.py`, `src/api/process_assets.py`, `src/api/health.py`, `src/api/auth.py`, `src/api/alerts.py`, every collector, and every storage adapter are byte-identical to their pre-merge `main` state.
- **No config changed.** `src/config.py` diff is empty across `8a501eb..ffee86d`. Default for `process_assets_enabled` is still `False`.
- **No seed, no migration, no schema, no env files** in the diff (`tests/`, `src/storage/`, `src/models/`, `alembic/`, `.env*` — all empty in the merge range).
- **`PROCESS_ASSETS_ENABLED` remains `False`** in every environment touched by this merge.
- **CMP overlay remains dormant.** `src/api/process_assets.py` is unchanged from PR #103; it returns `[]` for any caller when the flag is off; `/api/v1/assets` is byte-identical to its pre-merge response.
- **Deploy blast radius:** the dashboard static bundle `aevus-killdeer-3d.js`, the dormant Spline harness file `aevus-spline-twin.js`, the authoring-doc MD, and the new audit MD. The two JS files are only consulted by the browser when the live `/topology` endpoint is unreachable (`EQUIP`/`PIPES` fallback in `aevus-killdeer-3d.js`) or when the dormant Spline harness is explicitly activated by `window.AEVUS_SPLINE_URL` (currently never set). When the API is healthy — which it is, per `/health/ping` — none of the changed bytes are on the runtime request path.
- **Cache invalidation:** the `_TOPO_CACHE_KEY` bump `v18 → v19` causes a one-time re-fetch of `/topology` per operator browser at next load. No data side-effects.

## 10. Follow-up required

- **Authenticated smoke test of the four endpoints in §8** — to be completed only when a safely-sourced API key is available (approved local env var, or the documented AWS Secrets Manager path). Do not paste the key into chat. Once run, append the results back to this note rather than open a new doc.
- **No production flag flip yet.** `PROCESS_ASSETS_ENABLED` must stay `False` until the controlled-validation harness (ticket **K-T4** in the reconciliation doc) has been built and exercised against the flag-on path.
- **Next implementation lane is the next reconciliation ticket, not the flag flip.** Per `docs/implementation/killdeer_current_state_and_reconciliation.md` §6 the sequence is:
  1. ~~**K-T1** — fallback / Spline contract → 25 nodes / 26 edges~~ (✅ shipped in this merge).
  2. **K-T2** — refresh `drawings/VALIDATION_SUMMARY.txt` (closes V-1).
  3. **K-T3** — modeled / not-for-construction banner on Killdeer dashboard surfaces (closes T-2).
  4. **K-T4** — controlled-validation harness for `PROCESS_ASSETS_ENABLED=1` — documentation + procedure + rollback, **no flag flip in prod**.
  5. **K-T5** — `TwinNode.drawing_refs` design doc.
- Production enablement of `PROCESS_ASSETS_ENABLED` remains explicitly out of scope until its own program-control checkpoint.
