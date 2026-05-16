#!/bin/bash
# Aevus Deploy Script — copies staging to production with version tag
set -e

VERSION=$1
if [ -z "$VERSION" ]; then
  echo "Usage: ./deploy.sh v1.x.x"
  exit 1
fi

echo "=== Aevus Deploy: $VERSION ==="

# Build staging
echo "[1/4] Building staging..."
cd /home/ubuntu/aevus-testbed/dashboard-staging
bash build.sh

# Copy built files to production
echo "[2/4] Deploying to production..."
cd /home/ubuntu/aevus-testbed
cp dashboard-staging/api-client.js dashboard/api-client.js
cp dashboard-staging/Aevus_Console.html dashboard/Aevus_Console.html

# Commit and tag
echo "[3/4] Committing..."
git add -A
git commit -m "Deploy $VERSION"
git tag -a "$VERSION" -m "Deploy $VERSION - $(date '+%Y-%m-%d %H:%M')"

echo "[4/4] Done. Tagged: $VERSION"
git log --oneline -3
