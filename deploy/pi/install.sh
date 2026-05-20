#!/bin/bash
# ============================================================
# Aevus Edge Collector — Raspberry Pi install
# Sets up Python venv, dependencies, systemd unit, and the
# CAP_NET_BIND_SERVICE capability needed for the SNMP trap
# receiver to bind UDP 162 without running as root.
#
# Run ON THE PI (not on dev machine):
#   bash ~/aevus-testbed/deploy/pi/install.sh
#
# Idempotent — safe to re-run.
# ============================================================

set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/aevus-testbed}"
VENV_DIR="$REPO_DIR/.venv"
SERVICE_DIR="/etc/systemd/system"
PY_BIN_LINK="$VENV_DIR/bin/python3"

echo "==> Repo at: $REPO_DIR"
[ -d "$REPO_DIR" ] || { echo "ERROR: repo not found at $REPO_DIR — push the code first."; exit 1; }

echo "==> Installing apt prerequisites..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip python3-dev \
    libsnmp-dev snmp snmp-mibs-downloader \
    libcap2-bin \
    build-essential

echo "==> Creating Python venv at $VENV_DIR..."
[ -d "$VENV_DIR" ] || python3 -m venv "$VENV_DIR"

# Pre-create the directories the systemd hardening (ReadWritePaths=) references.
# Without these the service refuses to start with a 'No such file or directory'.
mkdir -p "$REPO_DIR/data" "$REPO_DIR/logs"
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
pip install --upgrade pip wheel
pip install -r "$REPO_DIR/requirements.txt"

echo "==> Granting CAP_NET_BIND_SERVICE to the venv Python so we can"
echo "    bind UDP 162 without running as root..."
PY_REAL="$(readlink -f "$PY_BIN_LINK")"
sudo setcap 'cap_net_bind_service=+ep cap_net_raw=+ep' "$PY_REAL"

echo "==> Installing systemd unit for the trap receiver (rendering for user '$USER' at '$REPO_DIR')..."
# Render the unit file with the actual user and repo path. The template
# is parametrized so any user (pi, admin, ubuntu, etc.) works without
# editing the source. The destination unit ends up at the standard
# /etc/systemd/system/ path with the user-specific values baked in.
TEMPLATE_FILE="$REPO_DIR/deploy/pi/aevus-trap-receiver.service"
RENDERED_FILE="$(mktemp)"
sed \
    -e "s|@AEVUS_USER@|$USER|g" \
    -e "s|@AEVUS_GROUP@|$USER|g" \
    -e "s|@AEVUS_REPO_DIR@|$REPO_DIR|g" \
    "$TEMPLATE_FILE" > "$RENDERED_FILE"
sudo install -m 644 "$RENDERED_FILE" "$SERVICE_DIR/aevus-trap-receiver.service"
rm -f "$RENDERED_FILE"
sudo systemctl daemon-reload
sudo systemctl enable aevus-trap-receiver.service

echo "==> Starting / restarting the service..."
sudo systemctl restart aevus-trap-receiver.service
sleep 2
sudo systemctl --no-pager status aevus-trap-receiver.service | head -20

echo ""
echo "==> Done. Smoke test from any host on the lab LAN:"
echo "    snmptrap -v2c -c aevus_trap $(hostname -I | awk '{print $1}') '' 1.3.6.1.6.3.1.1.5.1"
echo ""
echo "    Watch logs in real time:"
echo "    sudo journalctl -u aevus-trap-receiver.service -f"
