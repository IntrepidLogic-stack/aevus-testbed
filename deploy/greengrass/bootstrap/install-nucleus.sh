#!/bin/bash
# ============================================================
# AWS IoT Greengrass v2 Nucleus — installer for the Pi
#
# Two modes:
#   1. DEVELOPER MODE (default) — local-only, no AWS account
#      required. Lets you iterate on component recipes using
#      `greengrass-cli deployment create --merge ...` without
#      ever talking to AWS. Use this while AWS Activate credits
#      are still being confirmed.
#
#   2. PROVISIONED MODE — joins this Pi to a real AWS account
#      as an IoT Thing, IoT Role Alias, and Greengrass Core Device.
#      Required for cloud-side deployments via the Greengrass
#      console / CLI / Terraform.
#
# Run ON THE PI:
#   bash ~/aevus-testbed/deploy/greengrass/bootstrap/install-nucleus.sh           # developer mode
#   bash ~/aevus-testbed/deploy/greengrass/bootstrap/install-nucleus.sh --aws    # provisioned mode
#
# Idempotent — re-runs upgrade the nucleus in place.
# ============================================================

set -euo pipefail

MODE="developer"
if [[ "${1:-}" == "--aws" ]]; then
    MODE="provisioned"
fi

GREENGRASS_ROOT="/greengrass/v2"
GREENGRASS_USER="ggc_user"
GREENGRASS_GROUP="ggc_group"
NUCLEUS_VERSION="${NUCLEUS_VERSION:-2.14.0}"
NUCLEUS_URL="https://d2s8p88vqu9w66.cloudfront.net/releases/greengrass-nucleus-latest.zip"
INSTALL_TMP="/tmp/GreengrassInstaller"

echo "==> Aevus Edge — Greengrass v2 install (mode: $MODE, nucleus: $NUCLEUS_VERSION)"

# ── 1. Java 17 (Greengrass v2 requirement) ─────────────────────
echo "==> Installing Java 17..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends openjdk-17-jre-headless unzip curl python3 python3-venv

# ── 2. Create the Greengrass system user / group ───────────────
if ! getent group "$GREENGRASS_GROUP" >/dev/null; then
    sudo groupadd --system "$GREENGRASS_GROUP"
fi
if ! id -u "$GREENGRASS_USER" >/dev/null 2>&1; then
    sudo useradd --system --gid "$GREENGRASS_GROUP" --no-create-home --shell /usr/sbin/nologin "$GREENGRASS_USER"
fi

# Add the pi user to the ggc group so the deploy helper can write
# the deployment payload into Greengrass's working dirs.
if ! groups pi | grep -q "$GREENGRASS_GROUP"; then
    sudo usermod -aG "$GREENGRASS_GROUP" pi
fi

# ── 3. Download + stage the nucleus installer ──────────────────
echo "==> Downloading nucleus installer..."
sudo rm -rf "$INSTALL_TMP"
sudo mkdir -p "$INSTALL_TMP"
sudo curl -fsSL -o "$INSTALL_TMP/greengrass-nucleus.zip" "$NUCLEUS_URL"
sudo unzip -q "$INSTALL_TMP/greengrass-nucleus.zip" -d "$INSTALL_TMP/nucleus"

# ── 4. Install ─────────────────────────────────────────────────
if [[ "$MODE" == "provisioned" ]]; then
    : "${AWS_REGION:?Set AWS_REGION before running --aws (e.g. us-east-2)}"
    : "${AWS_ACCESS_KEY_ID:?Required for first-time provisioning}"
    : "${AWS_SECRET_ACCESS_KEY:?Required for first-time provisioning}"

    THING_NAME="${THING_NAME:-aevus-edge-$(hostname)}"
    THING_GROUP="${THING_GROUP:-AevusEdgeDevices}"

    echo "==> Provisioning as Thing '$THING_NAME' in group '$THING_GROUP' (region $AWS_REGION)..."
    sudo -E java -Droot="$GREENGRASS_ROOT" -Dlog.store=FILE \
        -jar "$INSTALL_TMP/nucleus/lib/Greengrass.jar" \
        --aws-region "$AWS_REGION" \
        --thing-name "$THING_NAME" \
        --thing-group-name "$THING_GROUP" \
        --component-default-user "$GREENGRASS_USER:$GREENGRASS_GROUP" \
        --provision true \
        --setup-system-service true \
        --deploy-dev-tools true
else
    echo "==> Installing in developer mode (no AWS provisioning, local CLI only)..."
    sudo java -Droot="$GREENGRASS_ROOT" -Dlog.store=FILE \
        -jar "$INSTALL_TMP/nucleus/lib/Greengrass.jar" \
        --component-default-user "$GREENGRASS_USER:$GREENGRASS_GROUP" \
        --provision false \
        --setup-system-service true \
        --deploy-dev-tools true
fi

# ── 5. Verify ──────────────────────────────────────────────────
sleep 3
echo "==> Nucleus status:"
sudo systemctl --no-pager status greengrass.service | head -15 || true

echo ""
echo "==> Greengrass CLI:"
"$GREENGRASS_ROOT/bin/greengrass-cli" --version || echo "CLI not yet on PATH; use $GREENGRASS_ROOT/bin/greengrass-cli directly"

echo ""
echo "==> Done. Next:"
echo "    bash ~/aevus-testbed/deploy/greengrass/package-artifacts.sh"
echo "    bash ~/aevus-testbed/deploy/greengrass/deploy-local.sh"
