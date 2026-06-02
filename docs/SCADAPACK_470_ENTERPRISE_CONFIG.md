# SCADAPack 470 — Enterprise Configuration Runbook (RemoteConnect)

**Device:** Schneider Electric SCADAPack 470 · FW **R3.3.5 / 9.11.5.15344** · S/N B327589
**Role:** Remote midstream RTU, polled by Aevus over the Trio JR900 radio link
**Target IP:** `192.168.88.21 / 24`, gw `192.168.88.1` (radio-bridged OT subnet)
**Poller:** edge Pi `192.168.88.254` (Modbus TCP), future Aevus DNP3 master
**Tool:** SCADAPack **RemoteConnect — full engineering edition** (NOT the Maintenance Tool)

> **End state:** a hardened, field-ready RTU that exposes its real diagnostics
> (supply voltage, battery, board temp) over Modbus/TCP + DNP3, and keeps
> working when its RJ45 is moved from the Catalyst to **RAD-02** — because it
> lives on the radio-bridged `.88` subnet and the Trio link bridges L2.

---

## ⚙️ The engineering insight (why `40001` reads 0)

`SYS_INFO_*` points (supply V, battery, temp) are **firmware diagnostics**.
RemoteConnect's *Status* tab reads them over its diagnostic channel — that's why
you see `24.5 Vdc` there. But the **Modbus server only serves the controller
object database**, and a `System Data`–sourced object's value does **not**
reliably propagate into a Modbus register unless the **running logic application
scans it**. An empty MAST program scans nothing → the object value never
refreshes → the Modbus register stays `0`.

**The correct, deterministic SCADAPack pattern** (what a Schneider engineer
does): create **logic-written "comms mirror" objects** mapped to Modbus
registers, and have a tiny MAST program copy each `SYS_INFO_*` diagnostic into
its mirror every scan. Logic-driven objects are guaranteed to update the
database, so the Modbus server always serves a live value. This is §6 + §7
below — it's the heart of the fix.

---

## 0. Pre-flight

1. **Use full RemoteConnect** (you confirmed it has the **Build** menu + Logic
   Editor). The Maintenance Tool can't build and must not be used here.
2. **Connect over the device's current IP.** It's at `192.168.88.21` now.
   `PC Communication Settings (CommDTM)` → TCP, host **`192.168.88.21`**, Modbus
   unit **1**. (SHOP-01 reaches it on its `192.168.88.10` interface.)
3. **Back up first.** `Read` the device → **Save Project As** `470_lab_<date>.prj`.
   Also: device **Status → Open Configuration Log** → save. Never commission
   without a rollback point.
4. Confirm **Online → Status** refreshes clean: SCADAPack 470, R3.3.5,
   "Normal operation", "Configured".

---

## 1. SCADAPack (controller node)  →  Configuration › SCADAPack

| Setting | Value | Why |
|---|---|---|
| Station / device name | `RTU-KILLDEER-01` (or your tag) | Identifiable in logs/DNP3 |
| Controller time source | NTP (see §3) | Time-stamped events must be accurate |
| Logic on startup | **Run** | RTU must auto-run logic after power loss |
| Retain/persist | Default | — |

**Verify:** name shows in the title bar + Online Status.

---

## 2. Physical I/O  →  Configuration › Physical I/O

Bench unit has no field transducers wired, so leave AI/DI/DO at defaults.
**Do not** map raw AI1–AI4 to Modbus yet — with nothing wired they'd read
0/garbage and pollute the pearl. (When a real pressure/level transmitter is
landed on AI1, that's when you scale + map it.)

---

## 3. IP Communication  →  Configuration › IP Communication  (the radio-ready network)

This is what makes the **RAD-02 cutover** work with zero reconfig.

### 3a. Ethernet Ports → **Ethernet 1**
| Field | Value |
|---|---|
| IP Address | **`192.168.88.21`** |
| Subnet Mask | `255.255.255.0` |
| Default Gateway | **`192.168.88.1`** (MikroTik) |

> The device lives on the **same subnet as the radio LAN**. RAD-01 (master) sits
> on the `.88` LAN; RAD-02 (subscriber) bridges Ethernet over RF. So a device on
> `.88.21` behind RAD-02 is transparently on the `.88` LAN — the Pi reaches it
> over the air with **no IP change**. That's the whole trick.

### 3b. Ethernet 2
**Disable** (single-homed RTU). Fewer interfaces = smaller attack surface +
no asymmetric-routing surprises over the radio.

### 3c. Services
Disable everything not used in the field:
- **Web/HTTP server: OFF** (unless you actively use it) — biggest attack surface.
- Keep **Modbus/TCP** (§4) and **DNP3** (§5) only.
- Leave **RemoteConnect/diagnostic** service ON (that's your mgmt path).

### 3d. Routing Table
Single default route `0.0.0.0/0 → 192.168.88.1`. No extra static routes needed
(flat `.88` OT subnet across the radio).

### 3e. NTP
Point to the **internal** MikroTik, not the internet:
- NTP server: **`192.168.88.1`** · enable.
- Air-gapped sites have no internet; internal NTP keeps DNP3 event timestamps
  correct. (Matches Task #137 — radios already use internal NTP.)

### 3f. Firewall → RTU Firewall  (enterprise hardening)
Allow inbound only from known hosts:
- `192.168.88.254` (edge Pi — Modbus 502 + DNP3 20000)
- `192.168.88.10` (SHOP-01 — RemoteConnect mgmt)
- Default-deny everything else.

**Verify (after write):** from the Pi `ping 192.168.88.21` and
`nc -zv 192.168.88.21 502` still pass; a host NOT in the allow-list is blocked.

---

## 4. Modbus  →  Configuration › Modbus › Server  (the Aevus poll interface)

| Setting | Value | Note |
|---|---|---|
| Modbus/TCP Server | **Enabled** | — |
| TCP Server Port | **502** | matches Pi relay |
| Unit Identifier | **1** | matches Pi relay |
| Addressing | **Standard** | — |
| Address Mode | **5 Digits** (4xxxx) | — |
| **Byte Ordering (32-bit)** | **High byte / Low word first (3412)** | **must match the Pi decode** |
| Swap Word Order (32-bit int) | No | — |
| Inactivity Timeout | 250 s | OK |

> The Pi relay decodes Float32 with this exact `3412` word order. If you ever
> change it, tell me — the decode must change too.

**Store and Forward:** leave default (not needed on a directly-polled RTU).

---

## 5. DNP3  →  Configuration › DNP3 › Outstation  (future Aevus DNP3 path)

Set this now so Aevus can later poll DNP3 (richer than Modbus — quality flags,
timestamps, unsolicited events):

| Setting | Value |
|---|---|
| Outstation address | **10** |
| TCP port | **20000** |
| Master address | **1** (Aevus) |
| Unsolicited responses | Enabled (to master `1`) |
| Event buffering | Class 1/2/3 as needed |

Map the same diagnostics to **DNP3 Analog Input points** (the Object Editor
**DNP3** tab → "DNP3 Point Number"). This gives Aevus a Modbus *and* DNP3 view.

---

## 6. Objects  →  Objects › Object Configuration  (point DB + comms mapping)

This is where the diagnostics get exposed. **We use the "comms mirror" pattern.**

### 6a. Source objects (already present — rows 9–12)
Leave these as the System-Data sources; we read them in logic:
- `SYS_INFO_InputSupplyVoltage` — REAL — supply Vdc
- `SYS_INFO_CPUmoduleTempC` — set **Logic Variable Type = `T_SPx70_REAL`** (it was `None`)
- `SYS_INFO_CPUmoduleTempF` — optional
- `SYS_CODE_StatusCode` — DINT — overall status

> **Important:** a System-Data object needs a **Logic Variable Type** to be
> readable in logic. Set TempC to `T_SPx70_REAL`, Logic Task `MAST`.

### 6b. Create the Modbus "mirror" objects (Add Object)
Add three **logic-sourced** REAL objects and give each a Modbus register:

| Name | Data Type | Source Type | Logic Var Type | Modbus Register | Modbus Data Type |
|---|---|---|---|---|---|
| `MB_SupplyVoltage` | Analog | **Logic** | `T_SPx70_REAL` | **40001** | **REAL (Floating Point)** |
| `MB_BoardTempC` | Analog | **Logic** | `T_SPx70_REAL` | **40003** | **REAL (Floating Point)** |
| `MB_StatusCode` | Analog | **Logic** | `T_SPx70_DINT` | **40005** | **DINT** |

(REAL = 2 registers each: `40001-40002`, `40003-40004`; DINT `40005-40006`.)

> Why mirrors instead of mapping `SYS_INFO_*` directly? Because logic-written
> objects are **guaranteed** to refresh the database every scan — no reliance on
> system-data auto-scan quirks. This is the deterministic, field-proven pattern.

---

## 7. Logic (MAST)  →  the marshalling program  (THE FIX)

Open **Configuration › SCADAPack x70 Logic → Open Editor**. In the **MAST**
task, add a Structured Text section `DiagMarshal`:

```iecst
(* === SCADAPack 470 diagnostics → Modbus mirror registers ===
   Runs every MAST scan. Copies firmware system diagnostics into the
   logic-written objects that the Modbus server exposes. This is what makes
   40001/40003/40005 carry a LIVE value instead of 0. *)

MB_SupplyVoltage := SYS_INFO_InputSupplyVoltage;   (* Vdc  -> 40001 REAL *)
MB_BoardTempC    := SYS_INFO_CPUmoduleTempC;        (* degC -> 40003 REAL *)
MB_StatusCode    := SYS_CODE_StatusCode;            (* code -> 40005 DINT *)
```

Then:
1. **Build → Rebuild All Project** → must report **`0 errors`** + "BUILT".
2. Close editor → **Update & Build Logic** on the Logic config page.

> If the editor complains a `SYS_INFO_*` name isn't a known variable, it's
> because its object lacked a Logic Variable Type — go back to §6a and set it,
> rebuild.

---

## 8. Security hardening (enterprise)

| Control | Action |
|---|---|
| **Device password** | Status → **Device Lock** → set an app password (store in the IL secret vault, NOT in this doc). x70 supports role-based security — use it. |
| **Unused services** | HTTP/web OFF (§3c). |
| **Firewall** | Allow-list Pi + SHOP-01 only (§3f). |
| **Modbus** | Server is **read-exposed** for diagnostics; do NOT enable Modbus *write* to coils/registers that drive logic. IL-009/P-008: no remote firmware/setpoint writes. |
| **DNP3** | Bind master to address `1`; consider DNP3 Secure Authentication (SAv5) for production. |

---

## 9. Build → Write → Verify

1. **Build → Rebuild All** → `0 errors`.
2. **Online** to **`192.168.88.21`** → confirm **Connected**.
3. **Write** → **all components** (config + logic) → no errors → device applies.
4. **Status → Refresh** → confirm "Configured", Normal operation.
5. **Verify over Modbus from the Pi** (this is the real proof):
   ```bash
   ssh admin@<pi> '/home/admin/aevus-testbed/.venv/bin/python - <<PY
   import struct; from pymodbus.client import ModbusTcpClient
   c=ModbusTcpClient("192.168.88.21",port=502,timeout=4); c.connect()
   r=c.read_holding_registers(0,count=6,device_id=1)   # 40001..40006
   x=r.registers
   sv=struct.unpack(">f",struct.pack(">HH",x[1],x[0]))[0]   # 3412 word order
   tc=struct.unpack(">f",struct.pack(">HH",x[3],x[2]))[0]
   print("raw",x,"| supplyV",round(sv,2),"| tempC",round(tc,2))
   c.close()
   PY'
   ```
   **Expect ~`24.5` and ~`44.0`** — not 0.

---

## 10. Radio cutover — RJ45 from Catalyst → RAD-02

Because the device is already on the `.88` subnet, the cutover is **physical +
radio**, no RTU reconfig:

### Pre-checks (Trio JR900 link)
- RAD-01 (master) + RAD-02 (subscriber) are **linked** (you have live SNMP from
  both — confirmed).
- Radios are in **transparent Ethernet bridge** mode (not serial-only), same RF
  network ID + encryption key, so the `.88` L2 crosses the air.
- RAD-02 has a free Ethernet/LAN port for the RTU.

### Cutover
1. Unplug the SCADAPack RJ45 from **Catalyst Fa0/2**.
2. Plug it into **RAD-02's Ethernet port**.
3. From the Pi:
   ```bash
   ping -c4 192.168.88.21        # now traverses the RF link (expect higher, stable latency)
   nc -zv 192.168.88.21 502
   ```
4. The pearl stays green; the Pi relay's `MODBUS LATENCY` rises from ~3 ms (wire)
   to the radio RTT — **that's the real over-the-air number for David.**

### If `.88.21` is unreachable after the move
The Trio radios aren't bridging L2 → fix in the radio config (TVIEW+/web UI):
set both to **bridge** mode, same network, confirm the subscriber forwards the
RTU's MAC. (Do not re-IP the RTU — the subnet is correct.)

---

## 11. Verification matrix (commissioning sign-off)

| Check | Pass criteria |
|---|---|
| Device identity | SCADAPack 470, FW R3.3.5, "Configured" |
| Ethernet 1 | `192.168.88.21/24`, gw `.88.1` |
| Modbus server | 502 open, unit 1, byte order 3412 |
| **Diagnostics over Modbus** | `40001`≈24.5 V, `40003`≈44 °C (from Pi) |
| DNP3 outstation | addr 10, port 20000 reachable |
| Firewall | only Pi + SHOP-01 allowed |
| Security | app password set, HTTP off |
| Logic | BUILT, runs on startup |
| **Radio cutover** | reachable on `.88.21` via RAD-02, latency = RF RTT |
| Aevus pearl | RTU-01 "SCADAPack 470", real supply V + temp, source=relay |

---

## Appendix — Modbus register map (as-built)

| Register (4xxxx) | Point | Type | Units | Pi decode |
|---|---|---|---|---|
| 40001–40002 | Supply voltage | REAL (3412) | Vdc | `struct '>HH'(r1,r0)` → `>f` |
| 40003–40004 | Board temp | REAL (3412) | °C | same |
| 40005–40006 | Status code | DINT (3412) | enum | `(r1<<16)|r0` |

Pi relay (`scripts/edge/scadapack_ingest_relay.py`) will read 40001–40006,
decode, and POST as `SUPPLY VOLTAGE`, `BOARD TEMP`, `RTU STATUS` vitals →
`score_rtu` weights real supply voltage → the pearl reflects true device health.

---
*Authored 2026-06-02. Commission top-to-bottom, then sign off §11.*
