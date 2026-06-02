# Edge SCADAPack 470 Modbus relay (Task #134 / #198)

Runs on the **edge Pi** (`aevus-edge` / IntrepidRAS, Tailscale `admin@100.93.143.71`).
Polls the SCADAPack 470 over Modbus TCP and POSTs comms-health to the Aevus
`/api/v1/ingest` endpoint, which the deployed **relay-overlay**
(`src/api/relay_overlay.py`) surfaces on the EFM/RTU pearl
(`aevus.intrepidlogic.io`). **READ-ONLY** — never writes the RTU (IL-009 / P-008).

## Why a relay (not the in-app collector)
The public dashboard is the EC2 instance; the Pi feeds it. The `/ingest`
→ relay-overlay path is the verified route to surface real lab telemetry on
the production pearl, independent of the MQTT/SQLite paths. This relay is a
standalone process — it does NOT touch `aevus.service`.

## Device / network facts (as deployed 2026-06-01)
- SCADAPack 470 @ **`192.168.88.21`** (re-IP'd from `172.16.1.200` via full
  RemoteConnect — empty logic app built to generate STA/APX/SIG, config written).
- Modbus TCP **:502**, unit id **1**. Reachable from the Pi (`0.4 ms`).
- Registers currently read `0x0000` (empty logic, no Modbus point map) → the
  relay reports **comms-health** (MODBUS LINK / LATENCY / COMM SUCCESS).
  To add real supply-voltage / battery / board-temp, map those x70 **system
  points** into the Modbus table in RemoteConnect, rebuild, rewrite — then
  extend `poll()` to decode them.

## Install on the Pi (as the `admin` user — NO sudo needed; linger is on)
```bash
# 1) copy the script
scp scripts/edge/scadapack_ingest_relay.py admin@<pi>:/home/admin/

# 2) install the user-systemd unit
mkdir -p ~/.config/systemd/user
cp scripts/edge/scadapack-relay.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now scadapack-relay.service

# 3) verify
systemctl --user is-active scadapack-relay.service   # -> active
tail -f /home/admin/scadapack_relay.log              # poll OK ... ingest 200
```

`linger=yes` is set for `admin`, so the service runs without an interactive
login and survives reboots.

## Verify it surfaced
```bash
curl -s -H "x-aevus-demo: true" \
  https://aevus.intrepidlogic.io/api/v1/assets/RTU-01 | jq '.vitals'
# MODBUS LINK / LATENCY / COMM SUCCESS, "source":"relay"
```
The EFM/RTU pearl on `/telecom` shows **RTU-01 "SCADAPack 470"**, `source=relay`.
Stop the service → after 180 s the overlay's freshness gate lapses and the
pearl reverts to the simulator (safe rollback).
