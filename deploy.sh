#!/usr/bin/env bash
# Aevus deploy — THIN WRAPPER. All deploy logic lives in deploy/deploy.sh, which
# is the script the webhook (src/api/deploy.py -> POST /api/v1/deploy/trigger)
# actually executes. This wrapper exists only so a manual `bash deploy.sh` runs
# the exact same path as the webhook.
#
# Task #179 root cause (fixed 2026-06-05): deploy logic was split across TWO
# scripts (root deploy.sh + deploy/deploy.sh); the webhook ran deploy/deploy.sh
# while every restart fix landed in the root one. Consolidated — do NOT add
# deploy logic here; edit deploy/deploy.sh instead.
set -euo pipefail
cd "$(dirname "$0")"
exec ./deploy/deploy.sh "$@"
