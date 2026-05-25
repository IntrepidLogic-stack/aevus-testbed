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
# ============================================================

set -euo pipefail

REPO=/home/ubuntu/aevus-testbed
DASHBOARD_FILES="dashboard/Aevus_Console.html dashboard/api-client.js dashboard/login.html"
DASHBOARD_DIRS="dashboard/icons dashboard/images"
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
log "[4/5] Validating + reloading nginx..."
if sudo nginx -t >/dev/null 2>&1; then
    sudo systemctl reload nginx
    log "    nginx reloaded"
else
    log "    ERROR: nginx -t failed; not reloading. Run 'sudo nginx -t' for details."
    exit 2
fi

# 5. Record deploy.
DEPLOY_SHA=$(sudo -u ubuntu git rev-parse --short origin/main)
log "[5/5] Deploy $VERSION complete. Served commit: $DEPLOY_SHA"
logger -t "$LOG_TAG" "deploy $VERSION commit=$DEPLOY_SHA"
