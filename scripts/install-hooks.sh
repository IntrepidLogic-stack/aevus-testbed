#!/usr/bin/env bash
# Install Aevus git hooks (Task #201 follow-up).
# Copies the version-controlled hook from scripts/git-hooks/ into
# .git/hooks/ so every clone can opt in with one command:
#   bash scripts/install-hooks.sh
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC="$REPO_ROOT/scripts/git-hooks/pre-commit"
DST="$REPO_ROOT/.git/hooks/pre-commit"
if [ ! -f "$SRC" ]; then
    echo "ERROR: $SRC not found" >&2
    exit 1
fi
cp "$SRC" "$DST"
chmod +x "$DST"
echo "✓ pre-commit hook installed → $DST"
echo "  (runs git-secrets + auto ruff format/fix on staged Python)"
