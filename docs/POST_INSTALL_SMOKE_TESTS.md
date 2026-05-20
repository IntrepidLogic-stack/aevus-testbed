# Post-Install Smoke Tests

Run these immediately after `bash ~/aevus-testbed/deploy/pi/install.sh` succeeds. Each test exercises one Phase 1-3 capability end-to-end. If any test fails, the diagnostic table at the bottom maps the symptom to the fix.

**Required:** a second host on the lab LAN (SHOP-01 works) for sending test traps and pings. The Pi alone can't fully smoke-test itself.

---

## Test 1 — Phase 1 SNMP trap receiver is alive

**On the Pi:**
```bash
sudo systemctl status aevus-trap-receiver
```
Expect `active (running)`. Then:
```bash
sudo journalctl -u aevus-trap-receiver -n 20 --no-pager
```
Look for the line `trap_receiver_started host=0.0.0.0 port=162`. That's the success signal.

**From SHOP-01** (PowerShell with net-snmp installed, or any Linux host on the LAN):
```bash
snmptrap -v2c -c aevus_trap <pi-ip> '' 1.3.6.1.6.3.1.1.5.1
```
(Replace `<pi-ip>` with the actual Pi IP — `192.168.88.252` or whatever `ip addr show` reports.)

**On the Pi**, watch journalctl in another terminal:
```bash
sudo journalctl -u aevus-trap-receiver -f
```
Within ~100ms of the snmptrap command you should see:
```
trap_received  event_type=coldStart source_ip=<your-ip> asset_id=None ...
```

`asset_id=None` is expected — the asset registry hasn't been seeded yet. We'll wire that in Test 5.

✅ Test passes if the trap is decoded and printed.

---

## Test 2 — Phase 1 receiver handles vendor traps gracefully

Send a made-up vendor OID — these come from real Trio / Schneider gear:
```bash
snmptrap -v2c -c aevus_trap <pi-ip> '' 1.3.6.1.4.1.5727.99.99.99
```

The Pi log shows the raw OID as the event_type. No crash, no alarm. This is the contract — unknown OIDs go into the audit trail but don't page anyone.

✅ Test passes if the trap is logged without errors.

---

## Test 3 — Phase 2 ICMP probe (standalone)

The systemd unit only runs the trap receiver. To test ICMP, run the probe standalone for ~30 seconds:

**On the Pi:**
```bash
~/aevus-testbed/.venv/bin/python3 -m src.collectors.icmp_probe \
    RTR-01=192.168.88.1 \
    SHOP-01=192.168.88.253
```

(Adjust IPs to whatever's actually on the lab LAN. `arp -a` will show you.)

Within ~3 seconds, every reachable target transitions `unknown → up`. Now power-off (or unplug the cable on) one of those devices.

Within ~3 more seconds you see:
```
RTR-01     192.168.88.1       up        → down      loss= 100.0%  rtt=  0.00ms
```

Re-power. Within ~5s:
```
RTR-01     192.168.88.1       down      → up        loss=  0.0%  rtt=  0.42ms
```

Ctrl+C to stop. ✅ Test passes if state transitions fire on both directions.

---

## Test 4 — Phase 3 DNP3 receiver (without a real SCADAPack)

The DNP3 receiver needs `dnp3-python` and a real outstation. Skip if the SCADAPack isn't on the network yet — just verify the module loads:

```bash
~/aevus-testbed/.venv/bin/python3 -c \
  "from src.collectors.dnp3_unsolicited import DNP3UnsolicitedReceiver; \
   r = DNP3UnsolicitedReceiver(asset_id='RTU-01', host='10.0.0.99'); \
   print('OK', r.binary_point_map.get(1))"
```

Should print: `OK {'metric': 'high_pressure_alarm', 'description': 'High pressure shutdown'}`.

If you get `ModuleNotFoundError: No module named 'dnp3_python'` — that's fine, the receiver lazy-imports it. Install when SCADAPack is online:
```bash
~/aevus-testbed/.venv/bin/pip install dnp3-python
```

When the SCADAPack IS on the network, run:
```bash
~/aevus-testbed/.venv/bin/python3 -m src.collectors.dnp3_unsolicited 192.168.88.21
```

And latch a Binary Input in the workbench. You should see:
```
→ [binary_input ] high_pressure_alarm    = True      flags=0x81  latency= 143.4ms
```

The `latency` value is the patent demo number.

✅ Test passes if either the module loads (no SCADAPack) OR a real DNP3 event arrives with sub-500ms latency (with SCADAPack).

---

## Test 5 — Asset registry seeding

The trap receiver needs an asset registry so it can map source IPs to asset IDs. Seed the lab inventory:

**On the Pi:**
```bash
~/aevus-testbed/.venv/bin/python3 scripts/seed_assets.py 2>&1 | tail
```

(If `seed_assets.py` doesn't exist on this branch, skip — the asset registry will be data-driven from the FastAPI app once it's running.)

After seeding, repeat Test 1's snmptrap. The journalctl entry now shows `asset_id=RAD-01` (or whichever matches the source IP) instead of `asset_id=None`.

✅ Test passes if the source IP correctly maps to an asset_id.

---

## Test 6 — Synthetic alarm injection (cloud roundtrip dress rehearsal)

This tests the full MQTT publish path without needing real hardware. **Requires Mosquitto** (Phase 4 §9 of `deploy/pi/README.md`):

```bash
sudo apt-get install -y mosquitto mosquitto-clients
echo -e 'listener 1883\nlistener 9001\nprotocol websockets\nallow_anonymous true' \
  | sudo tee /etc/mosquitto/conf.d/aevus.conf
sudo systemctl restart mosquitto
```

In one terminal, subscribe to everything:
```bash
mosquitto_sub -h localhost -v -t 'aevus/#'
```

In another, inject a fixture:
```bash
~/aevus-testbed/.venv/bin/python3 scripts/inject_synthetic_alarm.py \
    --broker 127.0.0.1 \
    --fixture ~/aevus-testbed/tests/lambda/fixtures/critical_high_pressure.json \
    --restamp
```

The subscriber should print the published envelope on `aevus/lab/RTU-01/alerts/critical` immediately.

✅ Test passes if the message round-trips through the broker.

---

## Test 7 — Latency metrics endpoint

If the full FastAPI app is running (separate from the trap receiver — needs `uvicorn` started against `src.main:app`):

```bash
curl http://localhost:8000/api/v1/metrics/latency | python3 -m json.tool
```

Expect a JSON response with `detection_latency_ms` and `rca_latency_ms` histograms (count=0 initially). This is the patent-demo metrics surface.

If the FastAPI app isn't started yet, that's expected — the trap-receiver systemd unit only runs the standalone trap listener. The full scheduler service is the next-tier deploy.

---

## Quick diagnostic table

| Symptom | Likely cause | Fix |
|---|---|---|
| `aevus-trap-receiver` status = `failed` | `setcap` didn't take; venv python isn't allowed to bind UDP 162 | Re-run `install.sh`. If still failing: `sudo setcap 'cap_net_bind_service=+ep cap_net_raw=+ep' $(readlink -f ~/aevus-testbed/.venv/bin/python3)` |
| No traps arriving despite `snmptrap` succeeding | Firewall on the Pi blocking UDP 162 | `sudo ufw allow 162/udp` or check `iptables -L -n` |
| `trap_from_unknown_source` warnings | Asset registry empty | Run Test 5's seed step |
| ICMP probe says "permission denied" | Neither `cap_net_raw` nor `ping_group_range` set | `echo 'net.ipv4.ping_group_range = 0 65535' | sudo tee /etc/sysctl.d/99-aevus-icmp.conf && sudo sysctl --system` |
| `ModuleNotFoundError: dnp3_python` | Lazy library, install when SCADAPack online | `~/aevus-testbed/.venv/bin/pip install dnp3-python` |
| Mosquitto port conflict on 1883 | Some other broker already bound | `sudo lsof -i :1883` to find it |
| Synthetic injector hangs | `aiomqtt` not installed in venv | `~/aevus-testbed/.venv/bin/pip install aiomqtt` |
| `git pull` fails on the Pi | Out-of-date branch state | `cd ~/aevus-testbed && git fetch origin && git reset --hard origin/claude/event-driven-edge-phases-1-7` |

---

## What to tell Claude when something fails

Paste the last 20 lines of:
```bash
sudo journalctl -u aevus-trap-receiver -n 20 --no-pager
```
Plus the exact command that failed and its error output. That's enough to diagnose almost everything.
