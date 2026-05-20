# Aevus Operator Runbook

**Single source of truth** for bringing the platform from cold metal to a working end-to-end demo. Every other doc in this repo is referenced by section below — start here, branch out as needed.

**Audience:** field tech, board demo operator, on-call NOC. Assumes Linux familiarity and SSH access to a Raspberry Pi.

**Time budget end-to-end:** ~6 hours for the first run, ~30 minutes for subsequent demos.

---

## 0. Pre-flight checklist

Before touching anything:

- [ ] **AWS Activate credit tier confirmed** — see `docs/AWS_ACTIVATE_CREDITS_CHECK.md`. *Required only for the cloud half of §6 onward.* The local half (§1-§5) works credit-free.
- [ ] **Raspberry Pi** powered, hostname `aevus-edge`, plugged into the lab LAN.
- [ ] **Lab hardware** powered:
  - MikroTik L009 — should already be at `192.168.88.1` per CLAUDE.md.
  - Cisco Catalyst 2960 — may need console config (see §3b).
  - Trio JR900 radios — serial config required first (§3c).
  - SCADAPack 470 — Modbus + DNP3 enabled.
- [ ] **A dev machine** (Mac or Windows + Git Bash) with the testbed-kit repo cloned, Python 3.11+, Terraform 1.7+ (for §6).
- [ ] **Network path** from dev machine to the Pi — direct SSH on the lab LAN, Tailscale, or RustDesk into SHOP-01.

---

## 1. Stand up the edge collector on the Pi (local-only)

### 1a. SSH to the Pi
Direct, via Tailscale, or via RustDesk → SHOP-01. Confirm:

```bash
ssh pi@aevus-edge   # or pi@192.168.88.252
python3 --version   # ≥ 3.11
```

If Tailscale isn't installed yet, do it now per `deploy/pi/README.md` §1. Pays off the first time the Pi's DHCP lease churns.

### 1b. Push the repo from your dev machine

```bash
cd ~/path/to/testbed-kit
./deploy/pi/push-to-pi.sh
```

Excludes the venv, caches, data files. Lands at `~/aevus-testbed/` on the Pi.

### 1c. Install on the Pi (systemd mode)

```bash
ssh pi@aevus-edge
bash ~/aevus-testbed/deploy/pi/install.sh
```

Installs apt deps + Python venv + sets `CAP_NET_BIND_SERVICE` and `CAP_NET_RAW` on the venv python. Installs the trap-receiver systemd unit. Idempotent — re-run after every push.

Verify:

```bash
sudo systemctl status aevus-trap-receiver
sudo journalctl -u aevus-trap-receiver -f
```

You should see `trap_receiver_started host=0.0.0.0 port=162`.

> **Alternative — Greengrass v2 mode:** if you prefer the managed runtime, skip 1c and follow `deploy/greengrass/README.md` §3 instead. Don't run both surfaces — they collide on UDP 162. Cutover instructions in `deploy/pi/README.md` §6.

---

## 2. Local Mosquitto (no-AWS dev mode)

Skip if you're going straight to AWS in §6.

```bash
ssh pi@aevus-edge
sudo apt-get install -y mosquitto mosquitto-clients
echo -e 'listener 1883\nlistener 9001\nprotocol websockets\nallow_anonymous true' | \
  sudo tee /etc/mosquitto/conf.d/aevus.conf
sudo systemctl restart mosquitto
```

Add to `~/aevus-testbed/.env`:
```
MQTT_ENABLED=true
MQTT_BROKER_HOST=127.0.0.1
MQTT_BROKER_PORT=1883
MQTT_TLS_ENABLED=false
MQTT_SITE_ID=lab
MQTT_CLIENT_ID=aevus-edge-lab-01
```

Restart the trap receiver service (or the full scheduler once running):
```bash
sudo systemctl restart aevus-trap-receiver
```

In another terminal, subscribe to verify:
```bash
mosquitto_sub -h localhost -v -t 'aevus/#'
```

---

## 3. Device configuration

Configure each device to publish to the Pi at `192.168.88.252`.

### 3a. MikroTik L009 (already on the network)
Follow `deploy/pi/README.md` §4a. Toggle a port to verify the trap arrives in journalctl within <1s.

### 3b. Cisco Catalyst 2960 (needs console config)
Follow `deploy/pi/README.md` §4b. Test with `shut` / `no shut` on a port.

### 3c. Trio JR900 (after serial config)
Follow `deploy/pi/README.md` §4c. Trio-specific OIDs surface as raw IDs in `event_type` until we extend `SNMP_TRAP_OIDS` — that's expected.

### 3d. Schneider SCADAPack 470 (Modbus + DNP3)
- SNMP traps (secondary): `deploy/pi/README.md` §4d.
- **DNP3 unsolicited** (primary, patent-relevant path): `deploy/pi/README.md` §5a. This is the build that delivers sub-500ms process alarm latency.

---

## 4. Local smoke test (no cloud yet)

### 4a. SNMP traps (Phase 1)
From any host on the lab LAN:
```bash
snmptrap -v2c -c aevus_trap 192.168.88.252 '' 1.3.6.1.6.3.1.1.5.1
```
The trap should appear in `journalctl -u aevus-trap-receiver -f` within ~100ms.

### 4b. ICMP probe (Phase 2)
Power off a registered device. The probe should classify it `down` within ~3 seconds:
```
RTU-01     192.168.88.21      up        → down      loss= 100.0%  rtt=  0.00ms
```

### 4c. DNP3 unsolicited (Phase 3) — patent demo
With the SCADAPack online and configured per §3d:
```bash
~/aevus-testbed/.venv/bin/python3 -m src.collectors.dnp3_unsolicited 192.168.88.21
```
In the SCADAPack workbench, latch a Binary Input (e.g. high_pressure_alarm). The event should arrive with `latency_ms` <500ms. **This is the patent demo number.**

### 4d. Synthetic alarm (no hardware needed)
If hardware isn't ready, exercise the alarm path with a fixture:
```bash
~/aevus-testbed/.venv/bin/python3 scripts/inject_synthetic_alarm.py \
    --broker 127.0.0.1 \
    --fixture tests/lambda/fixtures/critical_high_pressure.json \
    --restamp
```
The alarm appears on MQTT `aevus/lab/RTU-01/alerts/critical`.

---

## 5. Verify latency metrics

The platform tracks two rolling histograms — detection and RCA latencies — for the P-008 patent claim. Once events are flowing:

```bash
curl -s http://aevus-edge:8000/api/v1/metrics/latency | python3 -m json.tool
```

Look for:
- `detection_latency_ms.p95_ms` ≤ 500
- `rca_latency_ms.p95_ms` ≤ 3000 (only populates once cloud is live, §6)
- `patent_demo_claims.detection_within_target` is `true`

To reset between demo runs:
```bash
curl -s -X POST http://aevus-edge:8000/api/v1/metrics/latency/reset
```

---

## 6. AWS landing zone (cloud half)

**Gate:** Activate confirmed per `docs/AWS_ACTIVATE_CREDITS_CHECK.md`.

### 6a. Enable Bedrock model access (interactive, one-time)
AWS Console → Bedrock → Model access → Manage model access → enable Anthropic Claude Sonnet (and Haiku as fallback). Terraform can't accept the EULA on your behalf.

### 6b. Configure AWS CLI credentials
```bash
aws configure --profile il-admin
# Set region: us-east-2 (recommended for Texas latency)
```

### 6c. Apply Terraform
```bash
cd infra/terraform
export AWS_PROFILE=il-admin
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

This stands up the full landing zone: IoT Core Things + certs + policies, SiteWise asset models, audit/artifact buckets with Object Lock, KMS, CloudTrail, Bedrock RCA Lambda + IAM, Cognito identity pool. ~5–10 min on first apply.

Capture outputs:
```bash
terraform output iot_endpoint            # MQTT_BROKER_HOST for the Pi
terraform output cognito_identity_pool_id  # for the dashboard
terraform output sitewise_cabinet_assets   # SiteWise asset IDs
```

Per-device certs are written to `infra/terraform/.secrets/` (gitignored).

### 6d. Push certs + switch the Pi to cloud mode
```bash
curl -o /tmp/AmazonRootCA1.pem https://www.amazontrust.com/repository/AmazonRootCA1.pem
scp /tmp/AmazonRootCA1.pem pi@aevus-edge:~/aevus-testbed/.certs/
scp infra/terraform/.secrets/aevus-edge-lab-01.cert.pem pi@aevus-edge:~/aevus-testbed/.certs/
scp infra/terraform/.secrets/aevus-edge-lab-01.key.pem  pi@aevus-edge:~/aevus-testbed/.certs/
```

On the Pi, edit `~/aevus-testbed/.env`:
```
MQTT_ENABLED=true
MQTT_BROKER_HOST=<iot_endpoint from terraform output>
MQTT_BROKER_PORT=8883
MQTT_TLS_ENABLED=true
MQTT_CA_CERT_PATH=/home/pi/aevus-testbed/.certs/AmazonRootCA1.pem
MQTT_CLIENT_CERT_PATH=/home/pi/aevus-testbed/.certs/aevus-edge-lab-01.cert.pem
MQTT_CLIENT_KEY_PATH=/home/pi/aevus-testbed/.certs/aevus-edge-lab-01.key.pem
MQTT_CLIENT_ID=aevus-edge-lab-01
MQTT_SITE_ID=lab
```

Restart and watch:
```bash
sudo systemctl restart aevus-trap-receiver
sudo journalctl -u aevus-trap-receiver -f
```

You should see `mqtt_connected broker=<iot endpoint>:8883`.

### 6e. Verify the cloud round-trip
In the AWS IoT Core MQTT test client (Console → IoT Core → MQTT test client → Subscribe), subscribe to `aevus/lab/#`. Trigger an alarm per §4d. The MQTT message should arrive within seconds.

### 6f. Verify the RCA Lambda fires
Inject a synthetic critical alarm via §4d. Within ~3s:
- A new message appears on `aevus/lab/RTU-01/rca/<alert_id>` with the structured RCA narrative.
- CloudWatch Logs `/aws/lambda/aevus-rca` shows `rca_complete` with a confidence score and latency.
- An object lands in `s3://aevus-audit-.../rca/lab/RTU-01/<date>/...json` under Object Lock.

---

## 7. Dashboard

### 7a. Local mode (Mosquitto)
Open `dashboard/Aevus_Console.html` in a browser. Add the MQTT snippet from `dashboard/README.md` §4 right before `</body>`. Reload — the DevTools console should show MQTT connection messages.

### 7b. Cloud mode (IoT Core via Cognito)
Configure as `dashboard/README.md` §3b — needs the Cognito identity pool ID from §6c and a small init script to compute the SigV4-signed URL.

### 7c. Force-render the RCA panel for rehearsal
In DevTools console:
```js
window.AEVUS_RCA.render({
  alert_id: 'ALT-DEMO01',
  asset_id: 'RTU-01',
  latency_ms_alert_to_rca: 2143,
  rca: {
    probable_cause: 'Discharge pressure spike from downstream valve closure.',
    evidence: ['discharge_pressure 1442 PSI > 1400 critical threshold',
               'high_pressure_alarm asserted via DNP3 in 143ms'],
    severity: 'critical',
    recommended_action: 'Dispatch field technician to inspect downstream valve V-103.',
    confidence: 0.87,
    supporting_assets: ['RTU-01']
  }
});
```
The panel slides up with the "2.1s alert→RCA" latency badge and 87% green confidence bar.

---

## 8. End-to-end demo script (for board / advisory)

The story is **physical event → AI root cause in under 4 seconds.**

1. **Open the dashboard** in cloud mode. Both alarm list and RCA panel visible.
2. **Show the metrics tile** — `curl http://aevus-edge:8000/api/v1/metrics/latency | jq` projected on screen. Detection p95 = X ms, RCA p95 = Y s.
3. **Trigger the event** — physically latch high_pressure_alarm on the SCADAPack workbench (or `scripts/inject_synthetic_alarm.py --restamp` if the SCADAPack isn't online yet).
4. **Watch the timeline** unfold:
   - **t+0**: physical event.
   - **t+~150ms**: alarm appears in the dashboard alert list (DNP3 unsolicited → MQTT → MQTT-WSS).
   - **t+~2.5s**: RCA panel slides up with cause + evidence + recommended action.
5. **Refresh the latency metrics** — point at the histogram. *That's* the P-008 patent claim with live evidence.
6. **Talking points**:
   - Polling-only competitors blind at sub-5s.
   - LLM-blind operators can't match RCA latency.
   - The combination is the defensible invention.
   - IL-9000 interlock — read-only, no write paths to PLC/RTU firmware.

---

## 9. Common operator tasks

### Restart everything
```bash
sudo systemctl restart aevus-trap-receiver
# or under Greengrass:
sudo /greengrass/v2/bin/greengrass-cli component restart --names io.intrepid.aevus.trap-receiver
```

### Pull recent logs
```bash
sudo journalctl -u aevus-trap-receiver --since '5 min ago' --no-pager
sudo tail -f /greengrass/v2/logs/io.intrepid.aevus.dnp3-receiver.log
```

### Update code
```bash
# On dev machine:
./deploy/pi/push-to-pi.sh
# On Pi:
bash ~/aevus-testbed/deploy/pi/install.sh   # systemd
# OR
bash ~/aevus-testbed/deploy/greengrass/package-artifacts.sh && \
bash ~/aevus-testbed/deploy/greengrass/deploy-local.sh   # Greengrass
```

### Roll back AWS infra
```bash
cd infra/terraform
terraform plan -destroy
terraform apply -destroy
```
**Destroys nothing under S3 Object Lock** (audit bucket) — by design. For dev cleanup, set `force_destroy = true` on the audit bucket in `aws-audit.tf` and re-apply first.

### Add a new edge device
Edit `infra/terraform/variables.tf` `edge_devices` map. `terraform apply`. New cert is written to `.secrets/`. Push to the new Pi per §6d.

### Add a new site
Same — append to `var.sites` and `terraform apply`. Cognito policies expand automatically.

---

## 10. Doc map

| If you want to... | Read |
|---|---|
| Pre-spend AWS check | `docs/AWS_ACTIVATE_CREDITS_CHECK.md` |
| 7-phase coverage plan with cost estimates | `docs/MONITORING_COVERAGE_PLAN.md` |
| AWS landing zone architecture | `docs/AWS_LANDING_ZONE.md` |
| Pi systemd-mode deploy | `deploy/pi/README.md` |
| Pi Greengrass-mode deploy | `deploy/greengrass/README.md` |
| AWS Terraform applies | `infra/terraform/README.md` |
| Dashboard wiring | `dashboard/README.md` |
| You are here | `docs/OPERATOR_RUNBOOK.md` |

---

## 11. Emergency / incident contacts

- **Repo / code questions:** Dave Spencer (woody@intrepidlogic.io)
- **AWS account access:** root credentials in 1Password + safe (per IL deployment playbook)
- **IL-9000 violation suspected:** halt the deploy, escalate to Dave immediately. Any code path that writes to PLC/RTU firmware is a board-level issue.

---

## 12. Known gaps (today)

| Gap | Impact | Tracked at |
|---|---|---|
| No 14 days of training data yet → L4E disabled | No predictive anomaly scoring | `infra/terraform/aws-l4e.tf` (`var.l4e_enabled = false`) |
| Dashboard cloud mode requires manual SigV4 init script | Not single-click cloud demo | `dashboard/README.md` §3b |
| Trio JR900 serial config not done | No real RF telemetry yet | `deploy/pi/README.md` §4c |
| SCADAPack 470 not on lab network | DNP3 path can't be validated end-to-end with real hardware | Use `--dry-run` fixtures (§4d) |
| Multi-tenant operator auth not implemented | Cognito pool is unauth-only | Out of scope for current build |
