#!/bin/bash
# ============================================================
# Local Greengrass v2 deployment helper.
#
# Runs `greengrass-cli deployment create --merge ...` on the Pi
# using locally-staged recipes + artifacts. This is the
# developer-mode loop — no AWS round-trips required.
#
# Usage on the Pi:
#   bash ~/aevus-testbed/deploy/greengrass/deploy-local.sh
#
# Default: deploys all three Phase 1-3 components.
# Single component:
#   bash deploy-local.sh io.intrepid.aevus.trap-receiver
# ============================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
RECIPE_DIR="$REPO_DIR/deploy/greengrass/recipes"
ARTIFACT_DIR="$REPO_DIR/deploy/greengrass/artifacts"
GG_CLI="/greengrass/v2/bin/greengrass-cli"

# Filter to a single component if the user passed one.
FILTER="${1:-}"

if [ ! -x "$GG_CLI" ]; then
    echo "ERROR: Greengrass CLI not found at $GG_CLI."
    echo "Run install-nucleus.sh first."
    exit 1
fi

# Each component → its desired version.
declare -A COMPONENTS=(
    ["io.intrepid.aevus.trap-receiver"]="1.0.0"
    ["io.intrepid.aevus.icmp-probe"]="1.0.0"
    ["io.intrepid.aevus.dnp3-receiver"]="1.0.0"
)

# Build the --merge arg list.
MERGE_ARGS=()
for name in "${!COMPONENTS[@]}"; do
    if [ -n "$FILTER" ] && [ "$FILTER" != "$name" ]; then
        continue
    fi
    version="${COMPONENTS[$name]}"
    MERGE_ARGS+=("$name=$version")
done

if [ ${#MERGE_ARGS[@]} -eq 0 ]; then
    echo "ERROR: filter '$FILTER' did not match any component."
    echo "Known: ${!COMPONENTS[*]}"
    exit 1
fi

echo "==> Local Greengrass deployment"
echo "    Recipes:   $RECIPE_DIR"
echo "    Artifacts: $ARTIFACT_DIR"
echo "    Components: ${MERGE_ARGS[*]}"
echo ""

# Make sure artifacts have been packaged (zip files exist).
for spec in "${MERGE_ARGS[@]}"; do
    name="${spec%=*}"
    version="${spec#*=}"
    if ! ls "$ARTIFACT_DIR/${name}-${version}"/*.zip >/dev/null 2>&1; then
        echo "ERROR: no artifact zip for ${name}-${version}."
        echo "Run package-artifacts.sh first."
        exit 1
    fi
done

sudo "$GG_CLI" deployment create \
    --recipeDir "$RECIPE_DIR" \
    --artifactDir "$ARTIFACT_DIR" \
    --merge "${MERGE_ARGS[@]}"

echo ""
echo "==> Deployment submitted. Watch progress:"
echo "    sudo $GG_CLI deployment list"
echo "    sudo $GG_CLI component list"
echo ""
echo "    Logs:"
for spec in "${MERGE_ARGS[@]}"; do
    name="${spec%=*}"
    echo "    sudo tail -f /greengrass/v2/logs/${name}.log"
done
