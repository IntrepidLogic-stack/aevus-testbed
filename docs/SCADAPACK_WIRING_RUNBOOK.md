# SCADAPack 470 — Edge Modbus Wiring Runbook (Task #198 / #134)

**Status:** ✅ LIVE (2026-06-01) — re-IP'd to `192.168.88.21`, polled by the
edge Pi over Modbus, on the production EFM/RTU pearl. See "UPDATE 2 — 2026-06-01
EVENING" at the bottom (the authoritative as-built); earlier sections are
historical.
**Device:** Schneider Electric SCADAPack 470, now at **`192.168.88.21`**
(re-IP'd from its out-of-box `172.16.1.200` via full RemoteConnect).

---

## What's done (code side, headless)

- ✅ `SCADAPack470Collector` exists and degrades gracefully (5 s timeout,
  `is_reachable()` returns `False` on any error, clean `ConnectionError`).
- ✅ `_register_modbus_collectors()` added to `src/main.py`, gated on
  `modbus_enabled=true`. OFF by default.
- ✅ `settings.scadapack_ip` default corrected to `172.16.1.200`.
- ✅ `/ingest` now persists edge-pushed vitals to InfluxDB (Task #196) — so
  once the SCADAPack data flows, the historian (TRENDS) populates.
- ✅ Pearl scorer shows the EFM/RTU node **gray** until real telemetry
  arrives (Task #195 fix) — no misleading green on a silent device.

## What's blocked (field side — needs Woody / on-site)

The collector polls `172.16.1.200` over Modbus TCP. **It must run on the
EDGE Pi**, which is on the lab LAN. The EC2 backend (AWS) cannot route to a
`172.16.x` private IP, so this never runs on EC2.

### Step 1 — Confirm the Pi can reach the SCADAPack
The Pi is on `192.168.88.x`; the SCADAPack is on `172.16.1.x`. These are
**different subnets** — confirm there's a route.

```bash
# On the edge Pi:
ping -c 3 172.16.1.200
nc -zv 172.16.1.200 502        # Modbus TCP port
```

If no route: either (a) add a static route on the Pi / MikroTik, or
(b) move the SCADAPack onto the `.88.x` subnet, or (c) dual-home the Pi.

### Step 2 — Confirm the SCADAPack answers Modbus
```bash
# On the Pi, with the testbed venv active:
python3 -c "
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient('172.16.1.200', port=502)
print('connected:', c.connect())
r = c.read_holding_registers(40001, 4, slave=1)
print('error:' , r.isError() if hasattr(r,'isError') else 'n/a')
print('registers:', getattr(r, 'registers', None))
c.close()
"
```

If the registers don't match the documented map (suction @ 40001 etc.),
re-confirm the SCADAPack's register configuration before trusting values.

### Step 3 — Enable the collector on the Pi
Edit the **Pi's** `.env` (NOT EC2's):
```ini
MODBUS_ENABLED=true
SCADAPACK_IP=172.16.1.200
MODBUS_PORT=502
MODBUS_SLAVE_ID=1
POLL_INTERVAL_RTU=5
```
Then restart the edge service:
```bash
sudo systemctl restart aevus-edge   # or whatever the Pi's unit is named
journalctl -u aevus-edge -f | grep -i modbus
# expect: "modbus_collector_registered asset_id=RTU-01 host=172.16.1.200"
```

### Step 4 — Confirm data flows up
The edge pushes to `/api/v1/ingest` → which now writes to InfluxDB.
- Dashboard: the EFM/RTU pearl on `/telecom` should turn from gray to a
  real score within one poll cycle.
- Historian: TRENDS on RTU-01 should show real sparklines (suction,
  discharge, battery, vibration) after ~5–10 min of accumulation.

---

## IL-9000 reminder

This collector is **read-only**. It reads holding registers + discrete
inputs. It MUST NOT write setpoints, toggle coils, or push firmware to the
SCADAPack. Any future change touching SCADAPack writes requires the IL-9000
interlock check. (Patentable invention P-008.)

---

*Generated 2026-05-31. Code is ready; the remaining steps are field/edge
actions only Woody (or on-site) can perform.*

---

## UPDATE 2026-06-01 — SHIPPED via SHOP-01 relay (supersedes Pi-direct)

Field reality killed the Pi-direct assumption: the SCADAPack sits on
`172.16.1.200`, and the edge Pi (`192.168.88.x`) has **no route** to that
subnet. The one host on BOTH the RTU subnet and the internet is **SHOP-01**
(multi-homed; its `172.16.1.100` interface reaches the RTU). So SHOP-01 is the
Modbus relay — exactly the "shop PC polling SCADAPack" path `/ingest` was built
for.

### What was verified on the bench (2026-06-01)
- Catalyst `Fa0/2` → SCADAPack, MAC `0005.2103.ebbe` (OUI `00:05:21` =
  Control Microsystems / Schneider). ✅ identified
- `ping -S 172.16.1.100 172.16.1.200` → 4/4, 0% loss. ✅ reachable from SHOP-01
- `TcpClient` bound to `172.16.1.100` → `172.16.1.200:502` → **OPEN** ✅
- Raw Modbus FC3 read (8 holding regs @ 0) → valid response `01 03 10 00…`
  (function code `03`, not exception `83`) → **Modbus confirmed answering**,
  unit IDs 1 and 0 both respond. Registers read `0x0000` (bench unit, no field
  I/O configured) → only **comms-health** is real telemetry today.

### The pipeline (3 connections, all shipped)
1. **`scripts/scadapack_relay.ps1`** (runs on SHOP-01) — raw Modbus over a
   socket BOUND to `172.16.1.100`, measures latency + rolling comms-success,
   POSTs honest vitals (`MODBUS LINK`, `MODBUS LATENCY`, `COMM SUCCESS`; on
   failure `MODBUS LINK=0` + `COMMUNICATION FAULT ALARM=ACTIVE`) to
   `/api/v1/ingest`. **Read-only** — never writes the RTU (IL-009 / P-008).
2. **`src/api/relay_overlay.py`** — the missing consumer of `_relay_data`.
   Overlays FRESH (<180 s) relay vitals onto the matching registry asset in
   `/assets` AND the pearl chain. Additive + freshness-gated: with the relay
   off, behavior is byte-identical to before (simulator demo untouched).
3. **`pearls._find_efm_rtu`** — the EFM/RTU pearl now prefers a REAL-sourced
   (relay/Modbus) RTU over the seeded simulator EFM. Live SCADAPack → real
   pearl; relay off → falls back to prior behavior.

### Honesty note (important for the Rickerson show-back)
The bench RTU has no transducers wired, so the registers are genuinely zero.
The relay reports **device-health** (RTU reachable, Modbus answering, no comm
fault) → `score_rtu` → ~100 "good". It does NOT fake pressures or battery.
When real field I/O is configured, add the documented register decodes
(suction @ 40001 Float32, battery @ 40011, etc.) to `Invoke-ModbusRead` and
they flow through automatically.

### Run it on SHOP-01 (RustDesk → SHOP-01 PowerShell)
```powershell
# 1) Verify a single cycle (prints poll + ingest result):
powershell -ExecutionPolicy Bypass -File scadapack_relay.ps1 -Once

# 2) Run continuously:
powershell -ExecutionPolicy Bypass -File scadapack_relay.ps1

# 3) Install as a Scheduled Task at boot (run once, elevated):
$action  = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument '-ExecutionPolicy Bypass -WindowStyle Hidden -File C:\aevus\scadapack_relay.ps1'
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'AevusScadaPackRelay' -Action $action -Trigger $trigger -Principal $principal
```

Verify it surfaced: the EFM/RTU pearl on `/telecom` flips to the SCADAPack
(`asset_id=RTU-01`, label "SCADAPack 470") with `source=relay`, and `/assets/RTU-01`
shows `MODBUS LINK/LATENCY/COMM SUCCESS` vitals with `"source":"relay"`.
Stop the task → after 180 s the pearl reverts to the simulator (safe rollback).

---

## UPDATE 2 — 2026-06-01 EVENING — LIVE via edge-Pi relay (AS-BUILT)

The re-IP path won. Final as-built:

1. **Re-IP** (full RemoteConnect, not the Maintenance Tool — the Maintenance
   Tool can't build logic): created a fresh project from Catalog (CommDTM →
   SCADAPack x70), opened the Logic Editor, **Build → Rebuild All Project** on
   the empty default MAST program (`0 errors` → STA/APX/SIG generated), set
   Ethernet 1 = `192.168.88.21`, went Online to `172.16.1.200`, **Write**.
   Device rebooted onto `192.168.88.21`.
2. **Poll path:** edge Pi (`admin@100.93.143.71`) runs
   `scripts/edge/scadapack_ingest_relay.py` as user-systemd service
   `scadapack-relay.service` (linger on, survives reboot). Polls
   `192.168.88.21:502` every 30 s, POSTs comms-health to `/api/v1/ingest`.
3. **Surfacing:** the deployed `relay_overlay` flips the EFM/RTU pearl to
   RTU-01 "SCADAPack 470", `source=relay`, score 100, and writes to InfluxDB.

Verified live: `/assets/RTU-01` → MODBUS LINK/LATENCY/COMM SUCCESS (source
relay); `/pearls/killdeer` efm_rtu → RTU-01 SCADAPack 470, 100, good.

**Follow-ups:** (a) map x70 system points (supply V / battery / board temp)
into the Modbus table in RemoteConnect → extend `poll()` to decode → real
voltages on the pearl; (b) move the SCADAPack cable Catalyst Fa0/2 → RAD-02
Ethernet for the over-the-RF topology (same subnet, transparent bridge — keeps
working). See `scripts/edge/README.md`.
