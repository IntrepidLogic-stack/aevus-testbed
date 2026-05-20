#!/bin/bash
# ============================================================
# Push the testbed-kit repo to the Raspberry Pi from your dev
# machine (Mac, or SHOP-01 via Git Bash).
#
# Usage:
#   ./push-to-pi.sh [pi-user@pi-host]
#
# Defaults to pi@aevus-edge.local (mDNS) which works on a Mac
# if Bonjour is enabled, or via a Tailscale MagicDNS hostname
# once the Pi is on the tailnet.
#
# Excludes the venv, caches, and data — those live on the Pi.
# ============================================================

set -euo pipefail

DEST="${1:-pi@aevus-edge.local}"
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

echo "==> Pushing $REPO_DIR → $DEST:~/aevus-testbed/"

rsync -avz --delete \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude 'node_modules/' \
    --exclude '.git/' \
    --exclude 'data/*.db' \
    --exclude 'data/*.db-journal' \
    --exclude 'logs/' \
    --exclude '.DS_Store' \
    "$REPO_DIR/" "$DEST:~/aevus-testbed/"

echo ""
echo "==> Push complete. Next on the Pi:"
echo "    ssh $DEST"
echo "    bash ~/aevus-testbed/deploy/pi/install.sh"
