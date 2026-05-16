#!/bin/bash
# Aevus Dashboard Build Script
# Concatenates source modules and minifies

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$DIR/src/js"

echo "Building api-client.js..."

# Concatenate in order
cat "$SRC/00-globals.js" \
    "$SRC/01-core.js" \
    "$SRC/02-overview.js" \
    "$SRC/03-pid.js" \
    "$SRC/04-pages.js" \
    "$SRC/05-engines.js" \
    "$SRC/06-init.js" \
    > "$DIR/api-client.src.js"

echo "  Concatenated: $(wc -l < "$DIR/api-client.src.js") lines"

# Minify if terser is available
if command -v npx > /dev/null 2>&1; then
  npx terser "$DIR/api-client.src.js" \
    --compress drop_console=false,passes=2 \
    --mangle toplevel \
    -o "$DIR/api-client.js"
  echo "  Minified: $(wc -c < "$DIR/api-client.js") bytes"
else
  echo "  WARN: npx/terser not found, skipping minification"
  cp "$DIR/api-client.src.js" "$DIR/api-client.js"
fi

echo "Done."
