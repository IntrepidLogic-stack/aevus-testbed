#!/usr/bin/env bash
# Aevus Testbed — Project Scaffolding
# Run this once to create the directory structure.
# After this, open Claude Code: cd aevus-testbed && claude

set -e

echo "🔧 Scaffolding Aevus testbed project..."

# Directories
mkdir -p src/models src/collectors src/engine src/storage/migrations src/api
mkdir -p dashboard scripts tests docs data

# Python package markers
touch src/__init__.py src/models/__init__.py src/collectors/__init__.py
touch src/engine/__init__.py src/storage/__init__.py src/api/__init__.py

# Placeholder files (Claude Code will fill these in)
touch src/main.py src/config.py src/scheduler.py
touch src/models/asset.py src/models/alert.py src/models/prediction.py src/models/telemetry.py
touch src/collectors/base.py src/collectors/snmp_radio.py src/collectors/snmp_gateway.py
touch src/collectors/ethernetip_plc.py src/collectors/modbus_legacy.py src/collectors/sensor_proxy.py
touch src/engine/health_score.py src/engine/alert_engine.py src/engine/prediction.py src/engine/normalizer.py
touch src/storage/influx.py src/storage/sqlite_db.py
touch src/api/assets.py src/api/alerts.py src/api/health.py
touch src/api/diagnostics.py src/api/predictions.py src/api/ws.py
touch dashboard/api-client.js
touch tests/test_collectors.py tests/test_health_score.py tests/test_alert_engine.py tests/test_api.py

# Copy config template
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  ⚙  Created .env from template — edit with your lab IPs"
fi

# Virtual environment
if [ ! -d .venv ]; then
    python3 -m venv .venv
    echo "  🐍 Created .venv"
fi

echo ""
echo "✅ Scaffold complete. Next steps:"
echo ""
echo "  source .venv/bin/activate"
echo "  pip install -r requirements.txt"
echo "  claude"
echo ""
echo "  Then tell Claude Code:"
echo "  'Read CLAUDE.md. Start with Phase 1 — discover devices and build the SNMP radio collector.'"
echo ""
