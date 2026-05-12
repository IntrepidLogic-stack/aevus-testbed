#!/bin/bash
set -e
cd /home/ubuntu/aevus-testbed
echo "Pulling latest..."
git pull origin main
echo "Installing dependencies..."
.venv/bin/pip install -r requirements.txt --quiet 2>/dev/null || true
echo "Restarting service..."
sudo systemctl restart aevus.service
sleep 2
sudo systemctl is-active aevus.service
echo "Deploy complete"
