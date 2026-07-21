#!/usr/bin/env bash
# Aevus Testbed — Production Deploy Script (THE one the webhook runs)
#
# Invoked by the deploy webhook: POST /api/v1/deploy/trigger -> src/api/deploy.py
# runs THIS file (/home/ubuntu/aevus-testbed/deploy/deploy.sh). The root-level
# ./deploy.sh is just a thin wrapper that execs this — keep all deploy logic HERE.
#
# Task #179 root cause (found 2026-06-05): the webhook runs deploy/deploy.sh, but
# every "#179 restart fix" had been applied to the *root* deploy.sh, which the
# webhook never calls. So production kept using `systemctl restart --no-block`,
# whose queued job is cancelled when systemd tears down our cgroup — leaving the
# backend on STALE code. Plus the webhook is fire-and-forget, so rapid pushes
# spawned overlapping deploys that raced each other's restart.
#
# This version fixes all of it:
#   • flock      — serialize concurrent deploys (no more racing restarts)
#   • non-fatal on-box test — CI's gate job is authoritative; a flaky box re-test
#                  must never silently abort the restart and strand stale code
#   • systemd-run restart in a SEPARATE cgroup that VERIFIES health + RETRIES,
#                  so it survives our teardown and always lands the new code
set -euo pipefail

APP_DIR="/home/ubuntu/aevus-testbed"
VENV="$APP_DIR/.venv"
SERVICE="aevus"
HEALTH_URL="http://localhost:8000/api/v1/health/ping"
LOCK="/tmp/aevus-deploy.lock"

echo "╔══════════════════════════════════════╗"
echo "║   Aevus Deploy — $(date -u +%Y-%m-%dT%H:%M:%SZ)   ║"
echo "╚══════════════════════════════════════╝"

# ── Serialize: only one deploy at a time. The webhook is fire-and-forget, so
# overlapping pushes used to race (Task #179). Wait up to 90s for the lock, then
# bail — the holder already deploys origin/main (latest), so bailing loses nothing.
exec 9>"$LOCK"
if ! flock -w 90 9; then
  echo "⚠ Another deploy holds the lock (>90s) — bailing; the holder deploys latest."
  exit 0
fi

cd "$APP_DIR"

# ── Pull latest (full reset — guarantees src/, dashboard/, and this script match
# origin/main on disk before we restart).
echo "→ Pull origin/main..."
git fetch origin main
git reset --hard origin/main
COMMIT="$(git rev-parse --short HEAD)"
echo "  at commit $COMMIT"

# ── Deps
# Install with requirements.txt as a constraints file so the box installs the
# SAME locked tree CI validated (pyproject = what we depend on; requirements.txt
# = which transitive versions). Without the lock, `-e ".[dev]"` floated pyproject
# floors to newer versions than CI tested — the drift that froze deploys on
# 2026-07-08. CI's gate already ran this exact command on Linux before this
# webhook fired, so the lock is known-good here.
echo "→ Install deps (locked)..."
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -e ".[dev]" -c requirements.txt --quiet 2>&1 | tail -3 || echo "  (pip step non-fatal)"

# ── Restart: DETACHED so it survives our own cgroup teardown. We're a child of
# aevus.service, so a direct or `--no-block` restart dies with our cgroup (Task
# #179). Dispatch it into a SEPARATE, uniquely-named transient unit (owned by
# PID 1) that restarts the already-updated service and verifies health.
#
# ROOT CAUSE of the silent-stale-code outage (fixed here): the webhook runs THIS
# script with a 120s subprocess timeout (src/api/deploy.py). An on-box smoke test
# used to run HERE — a full pytest suite that grew past 120s — so the subprocess
# was killed mid-test, BEFORE ever reaching this restart. The early `git reset
# --hard` still landed the files, so prod got new code on disk but was never
# restarted. Fix: restart runs immediately after the dep install (well within
# 120s); the redundant on-box smoke test is removed — CI already ran the full
# suite as the deploy gate. (Contributing bug also removed: the old restart
# wrapper re-pulled via `sudo -u ubuntu git fetch` inside the unit, with no ubuntu
# HOME/SSH env, which hung; the reset above already synced HEAD, so no re-pull.)
RESTART_UNIT="aevus-restart-$(date +%s)-$$"
RESTART_CMD="systemctl restart $SERVICE; for i in \$(seq 1 30); do sleep 1; if curl -fsS --max-time 2 '$HEALTH_URL' >/dev/null 2>&1; then logger -t aevus-deploy \"restart healthy — serving $COMMIT\"; exit 0; fi; done; logger -t aevus-deploy \"restart UNHEALTHY 30s after start (commit $COMMIT)\"; exit 1"
echo "→ Restart $SERVICE — detached unit $RESTART_UNIT (commit $COMMIT)..."
if sudo systemd-run --collect --on-active=2 --unit="$RESTART_UNIT" /bin/bash -c "$RESTART_CMD"; then
  echo "✓ Restart dispatched to detached unit (restarts + verifies health)."
else
  echo "⚠ systemd-run dispatch FAILED — direct restart as last resort (may be cut short)."
  sudo systemctl restart "$SERVICE" || true
fi

echo "✓ Deploy $COMMIT dispatched at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "  Verify: curl https://aevus.intrepidlogic.io/api/v1/health/ping"
# flock releases when fd 9 closes on exit; the restarter runs independently.
