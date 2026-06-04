#!/usr/bin/env bash
# Aevus Testbed — Production Deploy Script
# Called by GitHub Actions or manually: ./deploy/deploy.sh
set -euo pipefail

APP_DIR="/home/ubuntu/aevus-testbed"
VENV="$APP_DIR/.venv"
SERVICE="aevus"
HEALTH_URL="http://localhost:8000/api/v1/health/ping"

echo "╔══════════════════════════════════════╗"
echo "║   Aevus Deploy — $(date -u +%Y-%m-%dT%H:%M:%SZ)   ║"
echo "╚══════════════════════════════════════╝"

cd "$APP_DIR"

# Pull latest
echo "→ Pulling latest from origin/main..."
git fetch origin main
git reset --hard origin/main

# Install deps
echo "→ Installing dependencies..."
source "$VENV/bin/activate"
pip install -e ".[dev]" --quiet 2>&1 | tail -3

# Run quick tests (skip integration tests needing live hardware)
echo "→ Running smoke tests..."
pytest tests/ -x -q -m "not integration and not slow" --tb=short 2>&1 | tail -10 || {
  echo "⚠ Tests failed — aborting deploy"
  exit 1
}

# Restart service — DETACHED.
#
# This script is launched by the webhook handler (POST /api/v1/deploy/trigger),
# which runs INSIDE aevus.service's cgroup. A plain `systemctl restart aevus`
# therefore stops the cgroup — killing THIS script — before the restart job
# completes, so the service kept running STALE code (the 2026-06-04 twin-ask 404
# + frame-20.1 staleness; Task #179). `--no-block` enqueues the restart job in
# systemd (PID 1), which completes independently of us being killed. ubuntu has
# NOPASSWD sudo, so this just works.
echo "→ Restarting $SERVICE (detached --no-block)..."
sudo systemctl restart --no-block "$SERVICE"
echo "✓ Restart queued (detached). Commit: $(git rev-parse --short HEAD)"
echo "  Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
# NOTE: no post-restart health check here — systemd stops our cgroup mid-script
# once it processes the queued restart, so anything after this line may not run.
# Verify health externally: curl https://aevus.intrepidlogic.io/api/v1/health/ping
