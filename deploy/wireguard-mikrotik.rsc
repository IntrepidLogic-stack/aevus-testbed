# ============================================================
# Aevus WireGuard Tunnel — MikroTik L009 Configuration
# Paste this into MikroTik terminal (WinBox or SSH)
# ============================================================
#
# Tunnel: MikroTik (10.99.0.2) ←→ AWS EC2 (10.99.0.1)
# Purpose: Route lab LAN (192.168.88.0/24) to Aevus cloud
# EC2 endpoint: 54.211.59.53:51820
# EC2 public key: a3emTurmQmA8y+HaHG3PHRpiQ8Swf0h6FKsZPwP6xVA=
#
# STEP 1: Create WireGuard interface
/interface wireguard add name=wg-aevus listen-port=51820 mtu=1420

# STEP 2: Get the MikroTik public key (COPY THIS — needed for EC2 side)
# Run this after Step 1:
#   /interface wireguard print
# Look for "public-key" — send that value to Dave/Claude to complete EC2 config

# STEP 3: Add the EC2 peer
/interface wireguard peers add \
    interface=wg-aevus \
    public-key="a3emTurmQmA8y+HaHG3PHRpiQ8Swf0h6FKsZPwP6xVA=" \
    endpoint-address=54.211.59.53 \
    endpoint-port=51820 \
    allowed-address=10.99.0.0/24 \
    persistent-keepalive=25s

# STEP 4: Assign tunnel IP
/ip address add address=10.99.0.2/24 interface=wg-aevus

# STEP 5: Add route to EC2 tunnel subnet (auto via connected, but explicit for clarity)
# The 10.99.0.0/24 route is added automatically by the address above

# STEP 6: Firewall — allow WireGuard traffic
/ip firewall filter add chain=input protocol=udp dst-port=51820 action=accept \
    comment="Allow WireGuard" place-before=0
/ip firewall filter add chain=forward in-interface=wg-aevus action=accept \
    comment="Allow WireGuard forward in" place-before=0
/ip firewall filter add chain=forward out-interface=wg-aevus action=accept \
    comment="Allow WireGuard forward out" place-before=0

# ============================================================
# VERIFICATION (run after both sides are configured):
#   ping 10.99.0.1    (should reach EC2)
#   From EC2: ping 10.99.0.2    (should reach MikroTik)
#   From EC2: ping 192.168.88.1 (should reach MikroTik LAN IP)
# ============================================================

# NOTES:
# - persistent-keepalive=25s keeps the tunnel alive behind NAT
# - The EC2 security group already allows UDP 51820 inbound
# - Once tunnel is verified, EC2 collectors can reach lab devices
#   at their 192.168.88.x addresses through the tunnel
# - After VLAN migration, update AllowedIPs to include 10.50.x.0/24
