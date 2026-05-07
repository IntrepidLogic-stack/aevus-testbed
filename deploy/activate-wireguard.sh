#!/bin/bash
# ============================================================
# Activate WireGuard tunnel on EC2
# Usage: ./activate-wireguard.sh <MIKROTIK_PUBLIC_KEY>
# ============================================================

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <MIKROTIK_PUBLIC_KEY>"
    echo "Get the key from MikroTik: /interface wireguard print"
    exit 1
fi

MIKROTIK_PUBKEY="$1"

echo "==> Updating /etc/wireguard/wg0.conf with MikroTik public key..."
sudo sed -i "s|# PublicKey = <MIKROTIK_WG_PUBLIC_KEY>.*|PublicKey = ${MIKROTIK_PUBKEY}|" /etc/wireguard/wg0.conf

echo "==> Enabling IP forwarding..."
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/99-wireguard.conf > /dev/null

echo "==> Starting WireGuard interface..."
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0

echo "==> WireGuard status:"
sudo wg show

echo ""
echo "==> Tunnel is UP. Test with: ping 10.99.0.2"
echo "    Once MikroTik side is configured, also try: ping 192.168.88.1"
