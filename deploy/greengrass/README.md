# Aevus Edge — Greengrass v2 Wrap

This is the **bridge step** between systemd-managed Python services on the Pi and a full AWS-managed edge fleet. Same Python code as the systemd deploy (`deploy/pi/`); same alarm logic; same hardware behavior. What changes is the runtime: each Phase 1-3 collector becomes a Greengrass v2 **component** with a recipe, lifecycle hooks, configuration parameters, and a managed deploy/rollback story.

**Why now:** Phases 1-3 are stable. Operational maturity (signed artifacts, fleet-wide config, OTA updates, deployment history, store-and-forward via Stream Manager) is the next thing we need before any pilot or federal pursuit.

**Why not later:** waiting compounds. Every new component built outside Greengrass becomes another thing to migrate. Better to lock the pattern now, with three components, than later with ten.

---

## 1. Two modes

| Mode | When | What it gives | What's needed |
|---|---|---|---|
| **Developer** (default) | Today — iterate locally on the Pi | `greengrass-cli deployment create --merge ...` for local-only deployments, no AWS round-trips | Nothing — Java 17, downloads the nucleus, runs offline |
| **Provisioned** | After AWS Activate credits confirmed | Same component model, but deployments roll out from the AWS console / Terraform / CLI to one or many cores | AWS account, IAM keys, region, Thing name + group |

We start in developer mode. Switch to provisioned once `docs/AWS_ACTIVATE_CREDITS_CHECK.md` clears.

---

## 2. Architecture

Three components, one per Phase 1-3 collector:

```
io.intrepid.aevus.trap-receiver   →  UDP 162 SNMP traps           (Phase 1)
io.intrepid.aevus.icmp-probe      →  1s layer-3 reachability       (Phase 2)
io.intrepid.aevus.dnp3-receiver   →  TCP 20000 DNP3 unsolicited    (Phase 3)
```

Each component:

- Owns its own Python venv inside `/greengrass/v2/work/<component>/`.
- Pulls only the protocol library it needs (`pysnmp`, `icmplib`, `dnp3-python`) at install time.
- Has its own capability grant (`CAP_NET_BIND_SERVICE` on the trap-receiver venv, `CAP_NET_RAW` on the ICMP probe venv).
- Reads its tunables from the recipe's `ComponentConfiguration` → environment variables → existing `src/config.py`.
- Handles `SIGTERM` cleanly: closes sockets, drains queues, exits in <15s.
- Logs to stdout → captured by Greengrass at `/greengrass/v2/logs/<component>.log`.

A fourth orchestrator component (publisher / alert-engine / IPC bridge) lands in the next phase. Today the three collectors run in **standalone smoke-print mode** — they prove the wiring end-to-end against real hardware, and the cutover to IPC-publishing into a central alert engine is a recipe-only change.

---

## 3. Bring-up (developer mode)

### 3a. On the Pi — install the nucleus

```bash
bash ~/aevus-testbed/deploy/greengrass/bootstrap/install-nucleus.sh
```

Installs Java 17, downloads the Greengrass v2 nucleus, creates `ggc_user` / `ggc_group`, sets up the systemd unit. Adds the `pi` user to the `ggc_group` so the deploy helper can write recipes/artifacts without sudo.

Verify:

```bash
sudo systemctl status greengrass
/greengrass/v2/bin/greengrass-cli --version
```

### 3b. From your dev machine — push the repo

```bash
./deploy/pi/push-to-pi.sh
```

Same rsync as the systemd deploy. Repo lands at `~/aevus-testbed/` on the Pi.

### 3c. On the Pi — package the artifacts

```bash
bash ~/aevus-testbed/deploy/greengrass/package-artifacts.sh
```

Builds three per-component zips under `deploy/greengrass/artifacts/`. Each zip contains only the subset of `src/` that component imports — no cross-pollination, no pulling in `pymodbus` for the ICMP component, etc. The slim `src/collectors/__init__.py` (no eager imports) is what makes per-component packaging clean.

### 3d. On the Pi — deploy

```bash
bash ~/aevus-testbed/deploy/greengrass/deploy-local.sh
```

Submits a single deployment with all three components merged in. Watch progress:

```bash
sudo /greengrass/v2/bin/greengrass-cli deployment list
sudo /greengrass/v2/bin/greengrass-cli component list
sudo tail -f /greengrass/v2/logs/io.intrepid.aevus.trap-receiver.log
```

### 3e. Smoke test

Same tests as the systemd deploy — they exercise the same code:

```bash
# Trap receiver (from another host on the lab LAN):
snmptrap -v2c -c aevus_trap 192.168.88.252 '' 1.3.6.1.6.3.1.1.5.1

# ICMP probe — check the log:
sudo tail -f /greengrass/v2/logs/io.intrepid.aevus.icmp-probe.log

# DNP3 receiver — toggle a Binary Input in the SCADAPack workbench
# and watch the latency_ms metric in:
sudo tail -f /greengrass/v2/logs/io.intrepid.aevus.dnp3-receiver.log
```

---

## 4. Cutover from the systemd deploy

The systemd unit (`deploy/pi/aevus-trap-receiver.service`) and the Greengrass component (`io.intrepid.aevus.trap-receiver`) both bind UDP 162 — only one can run at a time.

Before deploying Greengrass:

```bash
sudo systemctl stop aevus-trap-receiver
sudo systemctl disable aevus-trap-receiver
```

To roll back to systemd:

```bash
sudo /greengrass/v2/bin/greengrass-cli deployment create --remove io.intrepid.aevus.trap-receiver
sudo systemctl enable --now aevus-trap-receiver
```

The two deploys are mutually-exclusive but interchangeable — pick whichever surface you want to be in today. Greengrass wins long-term because of OTA, fleet config, signed artifacts, and audit log; systemd wins for raw simplicity until those matter.

---

## 5. Iterating on a component

Edit `src/collectors/snmp_trap_receiver.py` (or wherever), then:

```bash
# Repackage just that component (or all three — it's fast):
bash ~/aevus-testbed/deploy/greengrass/package-artifacts.sh

# Bump the version in the recipe YAML (e.g. 1.0.0 → 1.0.1),
# OR force-redeploy at the same version:
bash ~/aevus-testbed/deploy/greengrass/deploy-local.sh io.intrepid.aevus.trap-receiver
```

For production, every code change bumps the version. Greengrass keeps deployment history, so rollback is a one-line `--merge io.intrepid.aevus.trap-receiver=1.0.0`.

Configuration-only changes (e.g. swapping the SNMP community) don't touch the artifact — edit the recipe's `DefaultConfiguration` and redeploy.

---

## 6. Cloud-deploy path (when AWS Activate is confirmed)

### 6a. Provision the Pi as a Greengrass Core Device

```bash
export AWS_REGION=us-east-2
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export THING_NAME=aevus-edge-lab-01
export THING_GROUP=AevusEdgeDevices

bash ~/aevus-testbed/deploy/greengrass/bootstrap/install-nucleus.sh --aws
```

This re-provisions the existing local install: creates the IoT Thing, attaches it to the Thing Group, downloads the device certificate + private key, configures the token exchange role alias. The previously-deployed local components keep running.

### 6b. Publish components to the AWS account

For each recipe:

```bash
COMP=io.intrepid.aevus.trap-receiver
VERSION=1.0.0
ARTIFACT_BUCKET=aevus-edge-artifacts

# Upload the artifact to S3 (Object Lock + KMS encryption recommended).
aws s3 cp deploy/greengrass/artifacts/${COMP}-${VERSION}/aevus-trap-receiver.zip \
    s3://${ARTIFACT_BUCKET}/${COMP}/${VERSION}/aevus-trap-receiver.zip

# Edit the recipe: change the artifact URI from file:/// to s3://...
# Then publish:
aws greengrassv2 create-component-version \
    --inline-recipe fileb://deploy/greengrass/recipes/${COMP}-${VERSION}.yaml
```

### 6c. Create a deployment targeting the Thing Group

```bash
aws greengrassv2 create-deployment \
    --target-arn arn:aws:iot:${AWS_REGION}:<acct>:thinggroup/${THING_GROUP} \
    --deployment-name "aevus-edge-phase-1-2-3" \
    --components '{
        "io.intrepid.aevus.trap-receiver":{"componentVersion":"1.0.0"},
        "io.intrepid.aevus.icmp-probe":{"componentVersion":"1.0.0"},
        "io.intrepid.aevus.dnp3-receiver":{"componentVersion":"1.0.0"}
    }'
```

Or do all of the above via Terraform — recommended once Activate is confirmed; see `docs/AWS_LANDING_ZONE.md` §11 action items.

---

## 7. Files in this directory

```
deploy/greengrass/
├── bootstrap/
│   └── install-nucleus.sh          # one-time Greengrass v2 install on the Pi
├── recipes/
│   ├── io.intrepid.aevus.trap-receiver-1.0.0.yaml
│   ├── io.intrepid.aevus.icmp-probe-1.0.0.yaml
│   └── io.intrepid.aevus.dnp3-receiver-1.0.0.yaml
├── artifacts/                       # generated; gitignored
│   └── <component>-<version>/<name>.zip
├── package-artifacts.sh             # builds the zip artifacts
├── deploy-local.sh                  # `greengrass-cli deployment create --merge ...`
└── README.md                        # you are here
```

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `greengrass-cli: command not found` | Nucleus not installed, or CLI not in PATH | Use full path `/greengrass/v2/bin/greengrass-cli`; or rerun `install-nucleus.sh` |
| Component stuck in `INSTALLED` (never `RUNNING`) | Install script failed; venv didn't build | `sudo cat /greengrass/v2/logs/io.intrepid.aevus.<name>.log` |
| `PermissionError` on UDP 162 | `setcap` didn't run in the Install lifecycle | Confirm `RequiresPrivilege: true` in the recipe's Install stage |
| ICMP probe says "permission denied" | Neither raw-cap nor `ping_group_range` set | The Install stage sets both — rerun deployment with `--reset` |
| DNP3 install hangs for 10+ min | dnp3-python wheel building from source on ARM | Normal first-time. Increase `Timeout: 600` in the recipe if it still TIMEOUTS |
| Component logs to stdout but no Greengrass log file | Greengrass log rotation kicked in or component crashed instantly | Check `/greengrass/v2/logs/greengrass.log` for the deployment trace |
| Component runs but recipe config changes don't apply | Greengrass caches at deployment scope — need a new deployment | `sudo /greengrass/v2/bin/greengrass-cli deployment create --merge ${name}=${version}` again |

---

## 9. What's next after this lands

Per `docs/MONITORING_COVERAGE_PLAN.md`:

- **AWS IoT Core MQTT + SiteWise** — collectors publish to `aevus/{site}/{asset}/events/*` topics. SiteWise ingests via IoT Core rule.
- **Dashboard moves to MQTT-over-WSS subscriptions** — same UI, real-time channel from MQTT instead of FastAPI WebSocket.
- **Bedrock RCA Lambda** on critical events — invokes Claude Sonnet via Bedrock, returns a root-cause narrative.
- **SiteWise Lookout for Equipment (L4E)** piloted for vibration / RF anomaly.
- **CloudTrail + S3 Object Lock audit log** before any federal pursuit.
