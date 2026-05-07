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

# Restart service
echo "→ Restarting $SERVICE..."
sudo systemctl restart "$SERVICE"
sleep 4

# Health check
echo "→ Health check..."
if curl -sf "$HEALTH_URL" > /dev/null; then
  echo "✓ Deploy successful"
  echo "  Commit: $(git rev-parse --short HEAD)"
  echo "  Time:   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
else
  echo "✗ Health check FAILED"
  sudo journalctl -u "$SERVICE" --no-pager -n 20
  exit 1
fi
