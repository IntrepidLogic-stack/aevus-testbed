#!/bin/bash
# ============================================================
# Aevus Deploy Script — surgical GitOps deploy (v2)
#
# Pulls dashboard/* from origin/main and updates the served files.
# Preserves local Python edits, runtime cache files, and untracked
# operator backups — only touches files actually tracked in dashboard/.
#
# Invoked as either ubuntu OR root. If run as root, marks the repo
# as safe (otherwise git refuses operations on a non-root-owned
# repo). All git writes still happen as the ubuntu user so the SSH
# deploy key works and file ownership stays consistent.
#
# Invoked by:
#   • .github/workflows/ci-cd.yml via SSM Run Command (as ubuntu)
#   • Manually: bash /home/ubuntu/aevus-testbed/deploy.sh [version]
#
# ⚠️ CONTRACT — GIT IS THE ONLY SOURCE OF TRUTH FOR dashboard/ AND src/.
#   Every deploy runs `git checkout origin/main -- <whitelisted files>`, which
#   OVERWRITES those files on the box. Any change made by hand on EC2 to a
#   tracked dashboard/ or src/ file WILL BE SILENTLY WIPED on the next deploy.
#   => Never hand-edit tracked files on the server. Commit to main instead.
#   => Codify any out-of-band server config (radio IPs, firmware patches, etc.)
#      in IaC / committed scripts, not as live edits.
# ============================================================

set -euo pipefail

REPO=/home/ubuntu/aevus-testbed
DASHBOARD_FILES="\
  dashboard/Aevus_Console.html \
  dashboard/api-client.js \
  dashboard/login.html \
  dashboard/twin-showcase.html \
  dashboard/rad-hover-live.js \
  dashboard/aevus-3dpad-map.js \
  dashboard/three.min.js \
  dashboard/aevus-killdeer-3d.js \
  dashboard/aevus-process-strip.js \
  dashboard/aevus-spline-twin.js \
  dashboard/aevus-windsock.js \
  dashboard/award-map.html \
  dashboard/award-client.js \
  dashboard/favicon.svg \
  dashboard/manifest.json \
  dashboard/leaflet.min.js \
  dashboard/leaflet.min.css \
  dashboard/maplibre-gl.min.js \
  dashboard/maplibre-gl.min.css \
"
# Note: tests/test_dashboard_assets.py asserts every dashboard asset
# referenced by Aevus_Console.html is in this whitelist — so CI fails before
# a deploy that would leave a referenced asset missing in production (which
# is exactly how the Leaflet-404 outage happened 2026-05-30).
DASHBOARD_DIRS="dashboard/icons dashboard/images dashboard/brand"
LOG_TAG="aevus-deploy"
VERSION="${1:-v$(date +%Y.%m.%d)-auto}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# Handle "dubious ownership" if invoked as root: tell git this repo
# is safe even though it's not owned by the current user. Harmless
# when running as ubuntu (just adds a safe.directory entry).
git config --global --add safe.directory "$REPO" 2>/dev/null || true

log "=== Aevus Deploy: $VERSION ==="
cd "$REPO"

# 1. Fetch latest from origin (as ubuntu, where the SSH key lives).
log "[1/5] Fetching origin/main..."
sudo -u ubuntu git fetch origin main 2>&1 | sed 's/^/    /'

# 2. Capture state.
log "[2/5] Pre-deploy state:"
log "    HEAD:        $(sudo -u ubuntu git rev-parse HEAD)"
log "    origin/main: $(sudo -u ubuntu git rev-parse origin/main)"
CHANGED=$(sudo -u ubuntu git diff --name-only HEAD origin/main -- dashboard/ 2>/dev/null || true)
if [ -n "$CHANGED" ]; then
    log "    Changed dashboard files:"
    echo "$CHANGED" | sed 's/^/        /'
else
    log "    No dashboard changes between HEAD and origin/main."
fi

# 3. Surgically check out dashboard files from origin/main.
# Also refresh deploy.sh itself. If deploy.sh changed, re-exec immediately
# so the NEW logic applies in this same invocation (otherwise a deploy.sh
# fix needs two pushes to bite — bootstrap problem from the Rickerson
# Scale pearls 404 / Task #179). Skip the re-exec on the FIRST pass after
# this commit lands (no _RE_EXEC_GUARD set) so we don't infinite-loop.
PRE_DEPLOY_SH_SHA=$(sha256sum "$REPO/deploy.sh" 2>/dev/null | cut -d' ' -f1 || echo "")
sudo -u ubuntu git checkout origin/main -- deploy.sh 2>/dev/null || true
POST_DEPLOY_SH_SHA=$(sha256sum "$REPO/deploy.sh" 2>/dev/null | cut -d' ' -f1 || echo "")
if [ -n "$PRE_DEPLOY_SH_SHA" ] && [ "$PRE_DEPLOY_SH_SHA" != "$POST_DEPLOY_SH_SHA" ] && [ "${_AEVUS_DEPLOY_REEXEC:-0}" != "1" ]; then
    log "    deploy.sh self-updated mid-run — re-executing with new logic"
    export _AEVUS_DEPLOY_REEXEC=1
    exec bash "$REPO/deploy.sh" "$VERSION"
fi
log "[3/5] Checking out dashboard/ from origin/main..."
for f in $DASHBOARD_FILES; do
    if sudo -u ubuntu git ls-tree origin/main "$f" >/dev/null 2>&1; then
        sudo -u ubuntu git checkout origin/main -- "$f"
        log "    updated: $f"
    else
        log "    skipped (not in origin/main): $f"
    fi
done
for d in $DASHBOARD_DIRS; do
    sudo -u ubuntu git checkout origin/main -- "$d" 2>/dev/null && log "    updated dir: $d" || log "    skipped dir (no changes): $d"
done

# 4. Validate nginx config and reload. nginx -t writes to stderr;
# we check the exit code instead of grepping output.
log "[4/6] Validating + reloading nginx..."
if sudo nginx -t >/dev/null 2>&1; then
    sudo systemctl reload nginx
    log "    nginx reloaded"
else
    log "    ERROR: nginx -t failed; not reloading. Run 'sudo nginx -t' for details."
    exit 2
fi

# 5. Backend deploy: ALWAYS sync src/ from origin/main, then restart aevus.service
#    via a DETACHED transient unit.
#
# THE ROOT CAUSE (Task #179, finally): deploys are triggered by a webhook
# (POST /api/v1/deploy/trigger) handled BY aevus.service, so deploy.sh runs as a
# CHILD of aevus.service. A direct `systemctl restart aevus.service` therefore
# kills deploy.sh's own parent (and deploy.sh) mid-restart, before the restart
# completes — so the service kept running STALE code (the 2026-06-04 twin-ask 404,
# and the frame-20.1 staleness). Earlier "gating" theories were red herrings.
#
# Fix: dispatch the restart in a SEPARATE cgroup via `systemd-run` (with a 1s timer
# so this script finishes cleanly first). That transient unit survives aevus.service
# stopping, so the restart always completes. Fallbacks for hosts without systemd-run.
log "[5/6] Syncing backend (src/) and dispatching DETACHED restart..."
sudo -u ubuntu git checkout origin/main -- src/ 2>/dev/null || true
sudo -u ubuntu git checkout origin/main -- pyproject.toml 2>/dev/null || true
sudo -u ubuntu git checkout origin/main -- requirements.txt 2>/dev/null || true
# ORDER MATTERS (Task #179, take 2). The deploy is triggered by the
# /deploy/trigger webhook, so deploy.sh runs INSIDE aevus.service's cgroup.
# `systemctl restart --no-block` enqueues the job and returns 0, but when
# systemd stops aevus.service it tears down the whole cgroup — and the not-yet-
# started restart job gets cancelled with it. Result: the OLD process keeps
# serving stale code (the 2026-06-04 /process 404). So restart from a SEPARATE
# cgroup FIRST: `systemd-run` spawns a transient unit owned by PID 1 (outside our
# cgroup) on a short timer, so it survives our teardown and always completes.
# Fall back to --no-block, then a direct restart, for hosts without systemd-run.
if sudo systemd-run --collect --on-active=3 systemctl restart aevus.service 2>/dev/null; then
    log "    restart scheduled via systemd-run (+3s, separate cgroup) — survives our own teardown"
elif sudo systemctl restart --no-block aevus.service 2>/dev/null; then
    log "    restart queued via systemctl --no-block (fallback)"
else
    sudo systemctl restart aevus.service || true
    log "    restart issued directly (last-resort)"
fi

# 6. Record deploy.
DEPLOY_SHA=$(sudo -u ubuntu git rev-parse --short origin/main)
log "[6/6] Deploy $VERSION complete. Served commit: $DEPLOY_SHA"
logger -t "$LOG_TAG" "deploy $VERSION commit=$DEPLOY_SHA"
