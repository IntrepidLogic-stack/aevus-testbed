#!/bin/bash
# ============================================================
# Package the testbed-kit source into per-component zip artifacts
# that Greengrass v2 unpacks into each component's working dir.
#
# Each component gets only the src/ subset it imports. Keeps the
# artifact small and makes the dependency surface explicit.
#
# Run from anywhere (Mac, Pi, SHOP-01). Output lands in
# deploy/greengrass/artifacts/<component>-<version>/.
# ============================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="$REPO_DIR/deploy/greengrass/artifacts"

echo "==> Repo:    $REPO_DIR"
echo "==> Output:  $OUT_DIR"

# Shared src tree that every component needs — config, models,
# the alert engine, the base collector. Keeps each artifact small
# but functional.
SHARED_PATHS=(
    "src/__init__.py"
    "src/config.py"
    "src/models"
    "src/collectors/__init__.py"
    "src/collectors/base.py"
)

pkg() {
    local component="$1"
    local version="$2"
    local zip_name="$3"
    shift 3
    local extra_paths=("$@")

    local stage_dir="$OUT_DIR/${component}-${version}"
    rm -rf "$stage_dir"
    mkdir -p "$stage_dir/payload"

    echo ""
    echo "==> Packaging $component @ $version"

    # Copy the shared src skeleton.
    for p in "${SHARED_PATHS[@]}"; do
        local src="$REPO_DIR/$p"
        local dest="$stage_dir/payload/$p"
        mkdir -p "$(dirname "$dest")"
        if [ -d "$src" ]; then
            cp -R "$src" "$(dirname "$dest")/"
        else
            cp "$src" "$dest"
        fi
    done

    # Copy the component-specific paths.
    for p in "${extra_paths[@]}"; do
        local src="$REPO_DIR/$p"
        local dest="$stage_dir/payload/$p"
        mkdir -p "$(dirname "$dest")"
        if [ -d "$src" ]; then
            cp -R "$src" "$(dirname "$dest")/"
        else
            cp "$src" "$dest"
        fi
    done

    # Strip __pycache__ and *.pyc from the staged tree.
    find "$stage_dir/payload" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$stage_dir/payload" -type f -name "*.pyc" -delete

    # Zip — note that Greengrass expects the contents to be at the
    # root of the zip; the recipe references {artifacts:decompressedPath}.
    ( cd "$stage_dir/payload" && zip -qr "$stage_dir/$zip_name" . )
    echo "    → $stage_dir/$zip_name ($(du -h "$stage_dir/$zip_name" | cut -f1))"
}

# ── io.intrepid.aevus.trap-receiver ────────────────────────────
pkg io.intrepid.aevus.trap-receiver 1.0.0 aevus-trap-receiver.zip \
    "src/collectors/snmp_trap_receiver.py"

# ── io.intrepid.aevus.icmp-probe ───────────────────────────────
pkg io.intrepid.aevus.icmp-probe 1.0.0 aevus-icmp-probe.zip \
    "src/collectors/icmp_probe.py"

# ── io.intrepid.aevus.dnp3-receiver ────────────────────────────
pkg io.intrepid.aevus.dnp3-receiver 1.0.0 aevus-dnp3-receiver.zip \
    "src/collectors/dnp3_unsolicited.py"

echo ""
echo "==> Done. Artifacts in $OUT_DIR/"
ls -lh "$OUT_DIR"/*/
