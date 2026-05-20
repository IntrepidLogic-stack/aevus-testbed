# Merge plan: `claude/event-driven-edge-phases-1-7` → `main`

Concrete strategy for unifying the two branches without losing either side's work. Read this before running any merge commands.

---

## TL;DR

The two branches solve different problems:

- **`origin/main`** — 25+ commits of dashboard maturation, board-audit responses, API surface expansion (correlations, AI, weather, ingest, integrations, commands, reports), alarm shelving, ISA-101 faceplates, security hardening. This is the **operator-facing UX and breadth** branch.
- **`claude/event-driven-edge-phases-1-7`** — event-driven edge collectors (trap, ICMP, DNP3), MQTT publisher, AWS landing zone Terraform, Bedrock RCA Lambda, latency tracker, Greengrass v2 wrap. This is the **patent-relevant detection + AI** branch.

**They are complementary, not competing.** Most of my additions are net-new files; the merge is mostly conflict-free except in 4-6 cross-cutting modules (`scheduler.py`, `alert_engine.py`, `config.py`, `requirements.txt`, `src/api/__init__.py`, `src/main.py`).

Recommended merge: **rebase my branch on top of main** (not the other way around). Main is the further-evolved branch; my changes layer on top.

Estimated effort: **2-3 hours** of focused work. **Do not attempt during the live Pi deployment.**

---

## Inventory: what's on each side

### Pure additions from `claude/event-driven-edge-phases-1-7` (no conflict possible)
These files don't exist on `main` and merge cleanly:

```
src/collectors/snmp_trap_receiver.py
src/collectors/icmp_probe.py
src/collectors/dnp3_unsolicited.py
src/integrations/__init__.py
src/integrations/mqtt_publisher.py
src/integrations/topic_map.py
src/integrations/latency_tracker.py
src/api/metrics.py
infra/lambda/rca/*
infra/terraform/*
deploy/pi/*
deploy/greengrass/*
dashboard/mqtt-client.js
dashboard/rca-panel.js
dashboard/latency-widget.js
dashboard/README.md
docs/MONITORING_COVERAGE_PLAN.md
docs/AWS_LANDING_ZONE.md
docs/AWS_ACTIVATE_CREDITS_CHECK.md
docs/OPERATOR_RUNBOOK.md
docs/POST_INSTALL_SMOKE_TESTS.md
docs/applications/AWS_ACTIVATE_APPLICATION_DRAFT.md
docs/patent/P008_PATENT_PROVISIONAL_DRAFT.md
docs/MERGE_PLAN_main_vs_event_driven_edge.md   ← this file
scripts/inject_synthetic_alarm.py
scripts/export_l4e_training_data.py
scripts/bootstrap_l4e_model.py
tests/test_scheduler_offline.py
tests/test_scheduler_traps.py
tests/test_scheduler_icmp.py
tests/test_scheduler_dnp3.py
tests/test_scheduler_mqtt.py
tests/test_dnp3_unsolicited.py
tests/test_mqtt_topic_map.py
tests/test_latency_tracker.py
tests/lambda/__init__.py
tests/lambda/test_rca_prompt.py
tests/lambda/test_rca_handler.py
tests/lambda/fixtures/*.json
```

That's the bulk of the work. All net-additive.

### Conflict files (real merge work required)

| File | What my branch adds | What main adds | Resolution strategy |
|---|---|---|---|
| **`src/scheduler.py`** | trap consumer loop, ICMP consumer loop, DNP3 consumer loop, MQTT publisher integration, staleness sweep, partial-telemetry detection | Notifier engine, weather engine, comm-quality engine, correlator engine, deeper alarm-routing | **Keep main's structure**, port my consumer loops + integrations on top as additional methods. Each consumer is independent — they slot in next to the existing engines. |
| **`src/engine/alert_engine.py`** | `evaluate_offline()`, `evaluate_partial()`, `evaluate_event()` (traps), `evaluate_reachability()` (ICMP) | Likely alarm shelving + acknowledge-with-comment workflow per board audit commits | **Combine.** My new methods are additive (different alert keys). Main's shelving + ack semantics applied on top of the new alert types. |
| **`src/config.py`** | DNP3 / ICMP / MQTT / staleness config knobs | Notifier / weather / comm-quality / correlator config knobs | **Concatenate.** Both sides only added attributes; no overlapping keys. |
| **`requirements.txt`** | Loose pins (`>=` style), aiomqtt, icmplib added | Strict pins (exact `==` style) with full transitive lockfile | **Adopt main's strict pins**, add my new deps at appropriate pinned versions: `aiomqtt==2.3.0`, `icmplib==3.0.4`, `dnp3-python==0.1.5`. Re-lock with `pip-compile`. |
| **`src/api/__init__.py`** | `metrics_router` export | All the new routers (ai, weather, integrations, deploy, etc.) | **Concatenate.** Just add `metrics_router` to main's list. |
| **`src/main.py`** | `metrics_router` import + `include_router` line | All the new router imports + lifecycle hooks for the engines | **Concatenate.** Add the metrics line to main's includes. |
| **`src/collectors/__init__.py`** | Slimmed to only export `BaseCollector` (no eager imports) | Likely still eager-imports all collectors | **Discuss with Dave** — my slim version supports the per-component Greengrass artifacts. Main may need to retain eager imports for other reasons. Worst case: keep main's eager-import path AND add my new collectors to the eager list. |
| **`src/storage/sqlite_db.py`** | `get_asset_by_ip()` method | Likely additional schema migrations | **Add my method**, audit main's migrations for any column-name collisions with `ip_address`. |
| **`src/collectors/base.py`** | `expected_metrics` ClassVar, `@typing.final` on safe_poll | Likely unchanged | **Take my version**, easy. |
| **`src/collectors/{modbus_rtu,snmp_radio,snmp_router,simulator}.py`** | `expected_metrics` declared per collector | Likely additions for new device types | **Combine.** My `expected_metrics` is one extra class attribute per file. |
| **`tests/test_alert_engine.py`** | 6 new test classes for offline/partial/event/reachability | Likely alarm-shelving + ack tests | **Concatenate test classes.** No method-name collisions expected. |
| **`.gitignore`** | `deploy/greengrass/artifacts/` | Various other entries | **Concatenate.** |

---

## Step-by-step merge sequence

**Pre-flight (5 min):**
1. Confirm `main` is at a stable point — no in-flight commits expected during the merge window.
2. Confirm 217 tests still pass on `claude/event-driven-edge-phases-1-7`.
3. Tag the current state for safety: `git tag pre-merge-main-2026-05-20 origin/main`.

**Step 1 — checkout main and create the integration branch (1 min):**
```bash
git checkout main
git pull
git checkout -b merge/event-driven-edge-into-main
```

**Step 2 — cherry-pick the additions one commit at a time (60-90 min):**

```bash
# Bring over my 3 commits one at a time so conflicts surface in isolation:
git cherry-pick b8a7e09  # Phases 1-7 — the big one, expect conflicts
git cherry-pick 74d2047  # Polish round — fewer conflicts
git cherry-pick 607c079  # Runbook + widget + L4E scripts — almost all docs/scripts, near-clean
```

For each conflict file, follow the resolution-strategy column from the table above. **Run tests after each cherry-pick** — don't let conflicts pile up.

**Step 3 — re-lock requirements.txt (10 min):**
```bash
# Inside a fresh venv:
python -m venv .venv-merge
source .venv-merge/bin/activate
pip install pip-tools
# Author a requirements.in with the loose pins from my branch + main's loose pins
# Generate a fully pinned requirements.txt:
pip-compile requirements.in
```

**Step 4 — run the full test suite (5 min):**
```bash
python -m pytest -q --ignore=tests/test_api.py --ignore=tests/test_collectors.py
```
Expect 217+ passing. If main's tests need adjustment to accommodate the new alert types (e.g. shelving tests now have to consider OFFLINE alerts), fix in this step.

**Step 5 — exercise the patent path against the merged code (10 min):**
```bash
python -m pytest tests/lambda/test_rca_handler.py -v
python scripts/inject_synthetic_alarm.py --fixture tests/lambda/fixtures/critical_high_pressure.json --dry-run
```

**Step 6 — open a PR for human review (5 min):**
```bash
git push origin merge/event-driven-edge-into-main
gh pr create --base main --title "Merge event-driven edge (Phases 1-7) into main" \
  --body "$(cat <<'EOF'
Cherry-picks the 3 commits from claude/event-driven-edge-phases-1-7 onto current main.

See docs/MERGE_PLAN_main_vs_event_driven_edge.md for the conflict-resolution rationale.

Major additions:
- Event-driven edge collectors (SNMP traps, ICMP probe, DNP3 unsolicited)
- MQTT publisher + topic mapping
- AWS landing zone Terraform (IoT Core, SiteWise, Cognito, audit S3, KMS, CloudTrail)
- Bedrock RCA Lambda + tests
- Greengrass v2 component recipes + deployment helpers
- Latency tracker + /api/v1/metrics/latency endpoint
- Operator runbook + smoke tests
- P-008 patent provisional draft
- AWS Activate application draft
- L4E pilot Terraform + bootstrap scripts

217 tests passing. No changes to existing scheduler engines (notifier, weather, comm_quality, correlator) — net-additive.
EOF
)"
```

**Step 7 — delete the integration branch after merge (1 min):**
```bash
git checkout main
git pull
git branch -d merge/event-driven-edge-into-main
git push origin --delete claude/event-driven-edge-phases-1-7  # only if happy
```

---

## Risk inventory

| Risk | Likelihood | Mitigation |
|---|---|---|
| `requirements.txt` re-lock breaks one of main's existing services | Medium | Re-lock in a fresh venv, run `pytest` against the full suite. Treat any failure as a deps regression and pin to the version on main. |
| Slim `src/collectors/__init__.py` breaks a main consumer that depended on eager-imports | Low — no callers found, but main may have new ones | Grep main for `from src.collectors import X` other than `BaseCollector` before adopting the slim version. |
| Alarm shelving + new alert types interact badly (shelving a comms-loss vs. a threshold breach has different semantics) | Medium | Land the merge first with both behaviors intact; add a follow-up commit explicitly handling the cross-product. |
| Main's correlator engine duplicates partial-telemetry detection | Low-medium | Read main's correlator code before the merge; if there's overlap, prefer the main implementation and remove mine. |
| Test name collision in `tests/test_alert_engine.py` | Low | Tests are namespaced under classes; collisions are class-level, easy to rename. |

---

## What to NOT do

- **Don't `git push --force` to main.** Open a PR instead. Branch protection (per IL deployment playbook) should require it anyway.
- **Don't rebase main onto my branch.** Main is the longer-lived branch with 25+ commits; the loss-of-history risk is real.
- **Don't delete `claude/event-driven-edge-phases-1-7` until the merged PR lands AND the Pi deploy is confirmed working.** It's the rollback target if something goes sideways.
- **Don't attempt the merge while a live demo is in progress.** Hold for a quiet window.

---

## Owner

Dave reviews + approves this plan. Claude executes the merge in the next focused session (separate from the active Pi deployment).
