#!/bin/bash
# Aevus EC2 deploy hardening — run as ubuntu user
set -euo pipefail

echo "=== Installing nginx ==="
sudo apt-get update -qq
sudo apt-get install -y nginx

echo "=== Stopping old uvicorn process ==="
pkill -f "uvicorn src.main:app" || true
sleep 2

echo "=== Installing systemd service ==="
sudo cp /home/ubuntu/aevus-testbed/deploy/aevus.service /etc/systemd/system/aevus.service
sudo systemctl daemon-reload
sudo systemctl enable aevus.service
sudo systemctl start aevus.service

echo "=== Configuring nginx ==="
sudo rm -f /etc/nginx/sites-enabled/default
sudo cp /home/ubuntu/aevus-testbed/deploy/nginx-aevus.conf /etc/nginx/sites-available/aevus
sudo ln -sf /etc/nginx/sites-available/aevus /etc/nginx/sites-enabled/aevus
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx

echo "=== Status ==="
sudo systemctl status aevus.service --no-pager -l
sudo systemctl status nginx --no-pager -l
echo ""
echo "=== Done. Aevus running behind nginx on port 80 ==="
