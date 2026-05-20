# Aevus Edge — Raspberry Pi Bring-Up

This is the Pi deploy for the event-driven edge collectors:

- **Phase 1 — SNMP trap receiver** (UDP 162) — sub-second cable-unplug, cold-start, auth-failure detection.
- **Phase 2 — ICMP probe** — 1s layer-3 reachability check; distinguishes "device dead" from "agent dead" from "path broken".
- **Phase 3 — DNP3 unsolicited responses** — millisecond-latency process alarms from the SCADAPack 470 (high pressure, low battery, comm fault, all analog values). This is the P-008 patent path.

All three run as systemd-managed Python modules on the Pi. The full FastAPI scheduler service (which consumes events from all three and updates the dashboard) is the next deploy after Phases 1–3 stabilize against live hardware.

---

## 0. Prerequisites

- Pi powered on, networked into the lab LAN (per CLAUDE.md: `192.168.88.252`, hostname `aevus-edge`).
- SSH enabled on the Pi (`sudo systemctl enable --now ssh`).
- You can SSH from somewhere — direct from a Mac, or from SHOP-01 via RustDesk, or via Tailscale once §1 is done.

If you can't SSH yet, see **§1 Tailscale** below — it's the cleanest fix.

---

## 1. (Optional but recommended) Install Tailscale on the Pi

Once Tailscale is on the Pi, you (and Claude) can SSH to it from anywhere by hostname. This removes the SHOP-01-in-the-middle workflow and survives the lab DHCP lease churning the Pi's IP.

**On the Pi** (one time):

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh
# Follow the URL it prints to authenticate against your tailnet.
# Recommend logging in with the IL company account so future
# IL devices (Watchman, RF analyzer, etc.) join the same tailnet.
```

After that, the Pi is reachable from any tailnet member as `aevus-edge` (MagicDNS) regardless of what lab LAN IP it currently holds.

**On your Mac** (one time): install Tailscale from the App Store, sign in with the same account, enable MagicDNS in the admin console.

---

## 2. Push code to the Pi

**From your dev machine (Mac or SHOP-01):**

```bash
cd /path/to/testbed-kit
./deploy/pi/push-to-pi.sh                      # uses pi@aevus-edge.local
# OR with explicit host:
./deploy/pi/push-to-pi.sh pi@aevus-edge        # via Tailscale
./deploy/pi/push-to-pi.sh pi@192.168.88.252    # via lab LAN
```

This rsyncs the repo to `~/aevus-testbed/` on the Pi, excluding the venv, caches, and data files.

---

## 3. Install on the Pi

**SSH into the Pi:**

```bash
ssh pi@aevus-edge   # or pi@192.168.88.252
bash ~/aevus-testbed/deploy/pi/install.sh
```

Installs apt deps, builds the Python venv, grants `CAP_NET_BIND_SERVICE` to the venv Python (so we can bind UDP 162 without running as root), installs the systemd unit, and starts the service.

Idempotent — safe to re-run after every push.

**Verify it's running:**

```bash
sudo systemctl status aevus-trap-receiver
sudo journalctl -u aevus-trap-receiver -f
```

You should see `trap_receiver_started host=0.0.0.0 port=162` in the logs.

---

## 4. Configure each lab device to send traps to the Pi

Trap target: **the Pi's IP on the lab LAN** (currently `192.168.88.252`). Community string: **`aevus_trap`** (matches `SNMPTrapReceiver(community="aevus_trap")` in `src/collectors/snmp_trap_receiver.py`).

### 4a. MikroTik L009 (RouterOS)

WinBox terminal or SSH:

```routeros
/snmp community
add name=aevus_trap addresses=0.0.0.0/0 read-access=no security=none

/snmp
set enabled=yes contact="Dave Spencer / Intrepid Logic" location="Lab Cabinet" trap-version=2 trap-community=aevus_trap trap-generators=interfaces,start-trap

/snmp trap-target
add address=192.168.88.252 community=aevus_trap version=2c
```

**Test:** `/interface ethernet disable ether3` then `enable ether3` — you should see linkDown + linkUp traps in the Pi's journalctl within ~1 second.

### 4b. Cisco Catalyst 2960 (IOS)

Console:

```cisco
configure terminal
 snmp-server enable traps
 snmp-server host 192.168.88.252 version 2c aevus_trap udp-port 162
 snmp-server enable traps snmp linkdown linkup coldstart warmstart authentication
 snmp-server enable traps config
 snmp-server enable traps entity
end
write memory
```

**Test:** `shut` / `no shut` on a port, or reboot the switch.

### 4c. Trio JR900 (after serial config)

Through the JR900 management interface (web UI or serial console):

- SNMP → Enable agent
- SNMP → Communities → add `aevus_trap` (read/write as required by the firmware)
- SNMP → Trap destinations → add `192.168.88.252:162`, community `aevus_trap`, version 2c
- Enable trap categories: link state, cold start, RF link state, temperature, authentication failure

Vendor-specific OIDs (under `1.3.6.1.4.1.5727.*`) will arrive as raw OIDs in the `event_type` field until we extend `SNMP_TRAP_OIDS` with Trio-specific labels.

### 4d. Schneider SCADAPack 470 — SNMP traps (secondary path)

In the SCADAPack workbench:

- Configuration → SNMP Agent → Enable
- Community → read = `aevus_ro`, trap = `aevus_trap`
- Trap destinations → IP `192.168.88.252`, port `162`, version `v2c`
- Enable: cold start, warm start, auth failure, comm fault

The SCADAPack's **primary** alarm path is DNP3 unsolicited responses — see §5 below. SNMP traps from it are a redundant secondary path.

---

## 5. (Phase 3) SCADAPack 470 — DNP3 unsolicited responses

This is the patent-relevant path. The SCADAPack pushes Class 1/2/3 event reports to the Pi the instant a Binary Input changes state or an Analog Input crosses a deadband. Typical end-to-end latency from physical condition → alert fired: **50–500ms**. Compare to 5-second Modbus poll worst case.

### 5a. Configure the SCADAPack 470 outstation

In the SCADAPack workbench (TelePace Studio or Realflo):

**DNP3 Outstation settings:**
- Outstation address: `10`
- Master address: `1`
- TCP listen port: `20000`
- Allow connections from: `192.168.88.252` (the Pi)
- Link layer keep-alive: `60s`
- Application layer confirm timeout: `5s`

**Unsolicited responses — enable all three classes:**
- Class 1 (high priority) → high_pressure_alarm, low_battery_alarm, communication_fault
- Class 2 (medium) → compressor_running transitions
- Class 3 (low) → analog value changes (with deadband)

**Analog deadbands** (the change-magnitude that triggers an analog input event):
| Point | Metric | Deadband |
|---|---|---|
| AI0 | suction_pressure | 10 PSI |
| AI1 | discharge_pressure | 15 PSI |
| AI2 | flow_rate | 0.2 MCFD |
| AI5 | battery_voltage | 0.1 VDC |
| AI8 | vibration | 0.3 mm/s |
| (others) | — | 1% of full scale |

Tighter deadbands = more network traffic + faster detection. The values above are a sensible starting point; tune after the first few days of operational data.

**Save the outstation config to flash** so it survives a power cycle.

### 5b. Install the DNP3 library on the Pi

The library isn't pulled by default (heavy native deps). On the Pi:

```bash
~/aevus-testbed/.venv/bin/pip install dnp3-python
```

If the wheel build fails on the Pi (common with C++ deps on ARM), the fallback is:

```bash
sudo apt-get install -y libstdc++-12-dev cmake
~/aevus-testbed/.venv/bin/pip install --no-binary :all: dnp3-python
```

### 5c. Smoke test the receiver

Standalone, against the SCADAPack:

```bash
~/aevus-testbed/.venv/bin/python3 -m src.collectors.dnp3_unsolicited 192.168.88.21
```

Then in the SCADAPack workbench, manually toggle a Binary Input (e.g. assert high_pressure_alarm). You should see within ~200ms:

```
→ [binary_input ] high_pressure_alarm    = True      flags=0x81  latency= 137.4ms
```

The `latency` value is the difference between the device-stamped event time and when this process received it. **That's the patent-relevant metric** — anything sub-500ms is the value proposition.

### 5d. Configure the receiver in production

Add to `.env` on the Pi:

```
DNP3_UNSOLICITED_ENABLED=true
DNP3_RECONNECT_INTERVAL=5.0
DNP3_INTEGRITY_POLL_INTERVAL=300
DNP3_CONNECT_TIMEOUT=5.0
DNP3_KEEP_ALIVE_INTERVAL=60
```

The full scheduler service will register the DNP3 receiver for every RTU asset in the registry automatically once the main FastAPI service is brought up.

### 5e. Safety — IL-9000

The DNP3 receiver is **read-only**. No control commands, no operate functions, no firmware writes. If you ever see code that issues a DNP3 control (object groups 12, 41), it must be in a separate audited module with `IL_009_ENFORCED` enforcement. The patent claim depends on this constraint as well.

---

## 6. (Phase 2) ICMP probe — privileged vs unprivileged

---

## 5. (Phase 2) ICMP probe — privileged vs unprivileged

The probe uses `icmplib`. Two options for sending ICMP echo:

### Option A — Unprivileged DGRAM sockets (recommended for the Pi)

Set the kernel knob so non-root processes can send ICMP datagrams:

```bash
# One-time on the Pi
echo 'net.ipv4.ping_group_range = 0 65535' | sudo tee /etc/sysctl.d/99-aevus-icmp.conf
sudo sysctl --system
```

Then in `.env` on the Pi:

```
ICMP_PRIVILEGED=false
```

### Option B — Raw sockets via `CAP_NET_RAW`

The install script already grants `cap_net_raw` to the venv Python, so this works out of the box. In `.env`:

```
ICMP_PRIVILEGED=true
```

Both modes work; Option A is the cleaner systemd posture (no raw sockets needed) but requires the sysctl. Pick one — don't enable both.

**Smoke test the ICMP probe standalone:**

```bash
~/aevus-testbed/.venv/bin/python3 -m src.collectors.icmp_probe \
    RTR-01=192.168.88.1 \
    RAD-01=192.168.88.11 \
    RTU-01=192.168.88.21
```

You'll see state transitions printed when you pull a cable or power off a device:

```
RTU-01     192.168.88.21      up        → down      loss= 100.0%  rtt=  0.00ms
RTU-01     192.168.88.21      down      → up        loss=   0.0%  rtt=  1.42ms
```

Target latency to detect a power-off: **3 seconds** (3 consecutive missed pings at 1s cadence).

---

## 7. Smoke test from any host on the lab LAN (Phase 1 traps)

Install `snmp` if not already (`sudo apt install snmp` on Linux, `brew install net-snmp` on Mac), then:

```bash
snmptrap -v2c -c aevus_trap 192.168.88.252 '' 1.3.6.1.6.3.1.1.5.1
```

On the Pi:

```bash
sudo journalctl -u aevus-trap-receiver -f
```

You should see the trap decoded within ~100ms:

```
trap_received event_type=coldStart source_ip=<your-ip> ...
```

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Service starts then immediately exits | `setcap` didn't take, or venv Python is a symlink that changed | Re-run `install.sh` — it re-applies `setcap` |
| `Permission denied: ('0.0.0.0', 162)` | `CAP_NET_BIND_SERVICE` missing on the venv Python | `sudo setcap 'cap_net_bind_service=+ep' $(readlink -f ~/aevus-testbed/.venv/bin/python3)` |
| Traps sent but nothing appears in journalctl | Firewall on the Pi blocking UDP 162 | `sudo ufw allow 162/udp` (or `iptables -A INPUT -p udp --dport 162 -j ACCEPT`) |
| `trap_from_unknown_source` warnings | Asset registry doesn't have the device's IP yet | `python3 scripts/seed_assets.py` to populate the registry |
| Wrong community string | Device-side and Pi-side don't match | Check `community=aevus_trap` on both sides |
| MikroTik trap not firing on link change | `trap-generators` not set | `/snmp set trap-generators=interfaces,start-trap` |
| `PermissionError` from ICMP probe | Neither raw socket cap nor unprivileged DGRAM enabled | Either re-run `install.sh` (grants `cap_net_raw`) or set `net.ipv4.ping_group_range = 0 65535` (see §5) |
| ICMP probe reports all assets down | Outbound ICMP blocked at the gateway, OR wrong host IPs in asset registry | Test with `ping 192.168.88.1` from the Pi; check asset registry IPs match reality |
| `dnp3_library_not_installed` in logs | dnp3-python wheel not installed | `~/aevus-testbed/.venv/bin/pip install dnp3-python` |
| DNP3 connects but no events arrive | Unsolicited responses not enabled on outstation | In SCADAPack workbench: confirm Class 1/2/3 unsolicited enabled, master address = 1, allowed source = Pi IP |
| DNP3 events arrive but `latency_ms=n/a` | Outstation not stamping events with G2V2 (Binary Input Change with time) | Switch outstation event class to G2V2 / G32V7 in the point config |
| DNP3 reconnect loop | Outstation app-layer confirm timeout too short, or firewall dropping idle TCP | Confirm `keep_alive_interval=60` matches both sides; check Pi-side firewall for TCP 20000 outbound |

---

## 9. (Phase 4) Local Mosquitto for MQTT smoke testing before AWS

Until `docs/AWS_ACTIVATE_CREDITS_CHECK.md` clears and we apply the `infra/terraform/` landing zone, you can exercise the MQTT publisher against a local Mosquitto broker on the Pi.

### 9a. Install Mosquitto

```bash
sudo apt-get install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
```

Default config listens on localhost:1883, anonymous access. Fine for the lab; not for anything past the lab cable.

### 9b. Configure the publisher to use it

Add to `~/aevus-testbed/.env` on the Pi:

```
MQTT_ENABLED=true
MQTT_BROKER_HOST=127.0.0.1
MQTT_BROKER_PORT=1883
MQTT_TLS_ENABLED=false
MQTT_SITE_ID=lab
MQTT_CLIENT_ID=aevus-edge-lab-01
```

Restart the scheduler / Greengrass deployment.

### 9c. Subscribe and watch

In another terminal on the Pi:

```bash
mosquitto_sub -h localhost -v -t 'aevus/#'
```

Trigger a known-good event (toggle a port on the MikroTik, or send a test trap) and you should see structured JSON arrive on the right topic almost instantly.

### 9d. Cutover to AWS IoT Core

When Activate is confirmed and `terraform apply` succeeds, swap the `.env` per `infra/terraform/README.md` §3 — no code changes required, the publisher already supports both modes.

---

## 10. What's next

Phases 1, 2, and 3 are all built and tested on the dev side. Once they're verified against live lab hardware:

- **Greengrass v2 wrap.** Convert each edge module (trap receiver, ICMP probe, DNP3 receiver, plus the existing pollers) into a Greengrass v2 component with a recipe. Deploy via `git push` → component artifact → fleet rollout. No new functionality — just managed deploy / rollback / fleet config / store-and-forward when WAN is down.
- **IoT Core MQTT + SiteWise.** Components publish to `aevus/{site}/{asset}/events/*` topics. SiteWise ingests via IoT Core rule, holds the canonical asset model. Dashboard moves to MQTT-over-WSS subscriptions.
- **Bedrock RCA Lambda.** Triggered on critical alarms; pulls recent events + time-series + asset context, produces a root-cause narrative. The patent-relevant demo with DNP3 unsolicited as the input signal.
- **SiteWise Lookout for Equipment (L4E)** piloted alongside Bedrock for vibration/RF anomaly detection.

See `docs/MONITORING_COVERAGE_PLAN.md` and `docs/AWS_LANDING_ZONE.md` for the full sequence.
