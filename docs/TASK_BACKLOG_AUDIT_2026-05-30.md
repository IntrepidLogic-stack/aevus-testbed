# Aevus Task Backlog Audit — 2026-05-30

Snapshot taken end of session 2026-05-30 (Saturday).
Source: 152 tasks tracked via `mcp__ccd_session_mgmt__` task tools.
After today: **146 completed, 6 pending**.

This audit clusters the 152 tasks by theme, identifies the items where
"completed" hides nuance (rolled-back, replaced, or fragile), and flags
the genuinely-still-pending follow-ups.

---

## TL;DR

- **8 task clusters** account for ~95% of the work. Most clusters are
  fully delivered. Two clusters (Network Fleet, Federal/Funding) have
  unfinished real work behind their "completed" tasks.
- **9 tasks marked completed are deceptive** — they either rolled back,
  got replaced by a different approach, or reflect a partial deploy that
  needs revisiting. Listed below.
- **6 pending tasks** are all either user-action, blocked by external
  dependencies, or blocked by lab network topology.
- **No active virtual-persona references** in the task list itself
  (already cleaned per the global memory note dated 2026-05-21).

---

## Clusters

### 1. Event-driven edge build-out (#1–#22, #44–#45)
**Status:** Fully delivered.

SNMP trap receiver, ICMP probe, DNP3 unsolicited, MQTT publisher, topic
map, scheduler integration, smoke tests. 24 tasks all completed; the
implementation has been load-bearing through the entire 2026 work and
shipped through PRs #50, #59, #60 today.

**Audit note:** Solid. The MQTT publisher + scheduler are battle-tested.

### 2. AWS IoT + Bedrock RCA Lambda (#23–#33, #41–#42, #64, #82, #83)
**Status:** Fully delivered. **Source-vs-deploy drift fixed today (PR #59).**

15 tasks: IoT Core landing zone, SiteWise asset model, Bedrock RCA
Lambda (handler + prompt + context), Cognito Identity Pool, demo-drill
Lambda, P-008 patent draft. The RCA Lambda was deployed live but its
source had been abandoned on a branch — **PR #59 restored canonical
source today**. Combined with PR #61's Terraform module, the entire
edge → IoT → CloudWatch → SNS path is now IaC-managed.

**Audit note:** Strong. Any future RCA changes go through PR review.

### 3. Greengrass + edge component packaging (#16–#19, #25, #39)
**Status:** Delivered but unused operationally.

The Pi runs `aevus.service` (plain systemd) today, not Greengrass. The
Greengrass scaffolding (nucleus install, component recipes, artifact
packaging) was built but the production deploy went with systemd
because it's simpler and the use case didn't need component-level
isolation. The Greengrass code paths still exist; they aren't a fork
problem because the systemd path doesn't depend on them.

**Audit note:** ⚠️ Could be deleted if confidence is high that
Greengrass won't be revisited. Not blocking anything, but technical
debt — every future contributor wonders which path is canonical.
Recommend: explicit `docs/GREENGRASS_DEPRECATION.md` or remove.

### 4. Dashboard ↔ Pi bridge (#84–#85, #93–#100, #106–#108, #144, #145)
**Status:** Converged today (PR #58 / Task #148).

Six iterations: bookmarklet → nginx bridge → MQTT-over-WSS → poll
sidecar → broken pseudo-asset → REAL data via DynamoDB latest-state
overlay (Task #148, completed). The 2026-05-30 dashboard rendering
recovery (PRs #51-58) sits on top of this.

**Audit note:** ⚠️ **The dashboard recovery thread is convergent but
fragile.** PRs #51-58 added a 17-name safety net for bare-global
ReferenceErrors in `api-client.js`. **Long-term fix not done:** the
minified api-client.js still ships with un-declared globals that depend
on the shim. Any new `renderXxx` function reading a new bare name will
hit the same class of bug. Replace the safety net with a Proxy wrapper
or pre-process the JS to surface dependencies at build time.

**Recommendation:** Add `TASK_153: Replace dashboard global-shim with
Proxy catch-all` to convert the bug class from "occasional
ReferenceError" to "logged warning, render continues."

### 5. Lab hardware activation (#91, #92, #131–#140)
**Status:** Trio JR900s + MikroTik + Catalyst all live polling.

The radios (RAD-01, RAD-02) are configured, NTP'd to MikroTik, sending
SNMP traps + responding to polls. Hover overlay + uptime computation
shipped. Firmware tracking + chattering detection wired (PR #122-126).

**Audit note:** Solid. **One genuine pending:**
- **#134** SCADAPack 470 at 172.16.1.200 still unreachable from the lab
  LAN (no L3 route). Network topology change required.

### 6. Security + IAM hardening (#41, #50, #51, #57, #101, #104, #105, #112, #119, #150–#152)
**Status:** Multiple rounds of scope-down; all completed.

PowerUserAccess → least-privilege deploy role; SSH PAT → deploy key;
RustDesk relay self-hosted + in TF; il-deploy-cli 10 policies → 1 scoped;
IoT policy v3 ghost-clientId fix; Tara Bell hard lockout.

**Audit note:** Strong. **One historical concern:**
- **Tara Bell legal hold** still references "Aisha Williams (Counsel)"
  in past artifacts — global memory confirms Aisha is virtual, NOT real
  counsel. Any escalation needs REAL outside counsel first.

### 7. Email / notification path (#67, #86–#89, #114–#118)
**Status:** SNS + SES both live, tested end-to-end today.

Critical alerts route via SNS to chiefegr@ + woody@; SES branded HTML
emails; bounce/complaint reputation alarms; account-wide alarm audit
with TreatMissingData fixes. Today's MQTT-failure smoke test verified
delivery to both inboxes.

**Audit note:** Strong. One follow-up worth doing:
- **#71** SNS SMS path blocked on 10DLC carrier review (Task #72 status:
  REVIEWING since some unknown date). Check status weekly.

### 8. CI/CD + lint hygiene (#52, #53, #54, #55, #56, #110, #141, #142)
**Status:** Two paydown cycles; current state clean as of PR #56 today.

`ruff check` + `ruff format` both pass on main. Pre-commit hook
installed. Deploy.sh pulls from GitHub before copy; EC2 has a git repo
with read-only deploy key; SSM-based deploy + GitHub Deployments
tracking active.

**Audit note:** ⚠️ **9 pre-existing test failures** (not new) still red
in Aevus CI/CD's test step. Caught during PR #56. Documented in PR #56
but NOT yet fixed — a "spawn task" chip is still in the UI from earlier
this session. Test step blocks Aevus CI/CD from going fully green even
though lint+format steps now pass.

---

## "Completed but actually nuanced" — 9 items

| ID | Marked completed because... | Reality |
|---|---|---|
| #85 | "DEPLOYED then REVERTED" | The nginx bridge was rolled back same day for feature gap. Counted as work-done. |
| #97 | "PI-01 collector — deployed broke seed, ROLLED BACK" | Same pattern. Took until #106 to reconcile EDGE-01 vs PI-01 cleanly. |
| #98 | "Bridge pseudo-asset path BROKE awards dashboard, recovered" | The "completion" was the recovery, not the original work. |
| #109 | "Investigate diverged origin/main vs claude/edge" | Investigation done; **the divergence itself was paid down piecemeal across many later PRs** — finally closed by PR #59 today restoring RCA Lambda source. |
| #65 | "Dashboard MQTT-over-WSS wired (not deployed)" | Wired in code, never enabled. May not be wanted now that DynamoDB overlay path works. Worth deciding to either ship or rip. |
| #29 | "L4E pilot Terraform + bootstrap docs" | TF + docs landed. **L4E pilot itself never actually ran** (waiting on real telemetry baseline; tracked separately if ever needed). |
| #16-#19 | Greengrass scaffolding | See Cluster 3 — built, unused. |
| #124 | "Run-hours + maintenance-due (deferred — needs SCADAPack online)" | Truly deferred until #134 resolves the SCADAPack network issue. |
| #130 | "Pi state divergence — full reconciliation needed" | Reconciliation steps were done, but the broader edge-vs-cloud state model is still nuanced. Today's PR #59 + #61 hardened it but not closed. |

---

## Pending (6) — what's actually blocking each

| ID | Pending | Block |
|---|---|---|
| **#66** | Patent demo screencap + video | USER hands — needs you to record |
| **#69** | Tailscale trial → free vs paid decision | USER decision (11 days remaining) |
| **#71** | SNS SMS path | EXTERNAL — 10DLC carrier review |
| **#111** | Calendar nudge ~2026-06-10 (Tailscale) | USER calendar |
| **#113** | Resubmit AWS Activate Portfolio | USER form |
| **#134** | SCADAPack 470 polling | NETWORK — no L3 route to 172.16.1.200 |

---

## Recommended new tasks

- **#153** Replace dashboard global-shim with Proxy catch-all (closes
  Cluster 4 bug class structurally)
- **#154** Fix 9 pre-existing test failures (auth + reports endpoints)
  so Aevus CI/CD goes fully green
- **#155** Decide Greengrass: rip or document deprecation (Cluster 3)
- **#156** Decide MQTT-over-WSS dashboard transport: ship or rip (#65)
- **#157** Capture remaining out-of-band AWS into Terraform (IoT thing
  + cert attachment, S3 audit bucket, Bedrock Lambda resource itself,
  aevus-critical-alerts SNS topic + subscriptions) — completes Task
  #149 fully

---

## Lessons captured

1. **Deploy without committing source = drift.** The RCA Lambda case
   (Tasks #80, #82 updated AWS, never reached main) and the IoT policy v3
   case (created via CLI, captured today in PR #61) both proved the
   need for: "no AWS resource change without TF state."

2. **Bug-class fixes beat individual bug fixes.** PR #53's 17-name safety
   net was more durable than fighting each undeclared global one by
   one — but a Proxy would be even more durable (recommended task #153).

3. **Self-healing > alarming.** Today's MQTT half-open work added BOTH
   in-process recovery (PR #57) AND alarm visibility (PR #60). The
   in-process recovery prevented the 2026-05-29 outage from recurring
   even if no one reads the alarm email.

4. **Document the operator quirk.** AWS IoT Rule substitution evaluates
   the inbound message, not the SELECT projection. Cost us ~45 min of
   debugging today. Now captured in PR #62's commit body + TF comment.

---

## Glossary — task tool conventions used

- **completed** — work was done AND verified live (or the artifact
  exists). Not necessarily still operational; see "nuanced" list above.
- **pending** — explicit blocker exists; not just unstarted.
- **virtual personas** — see global memory note 2026-05-21. None
  cited as authority in any active task here; historical references
  in completed tasks are documented record only.
