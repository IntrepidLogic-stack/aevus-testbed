#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/aevus-testbed
git pull origin main
source .venv/bin/activate
pip install -q -r requirements.txt
sudo systemctl restart aevus
echo "deploy complete at $(date)"
