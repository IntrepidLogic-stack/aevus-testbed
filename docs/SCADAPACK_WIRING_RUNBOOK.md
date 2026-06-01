# SCADAPack 470 — Edge Modbus Wiring Runbook (Task #198 / #134)

**Status:** Code-ready, blocked on field steps.
**Device:** Schneider Electric SCADAPack 470, found at **172.16.1.200**
(NOT the original `.88.21` plan — it lives on a different lab subnet).

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
