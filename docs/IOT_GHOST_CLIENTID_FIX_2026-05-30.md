# IoT Ghost ClientId Fix — 2026-05-30

## Task #152: Find + kill the "ghost" holding MQTT clientId `aevus-edge-needville`

## Symptom (historical)
The Pi's MQTT publishing stopped ~2026-05-29 00:56 UTC (Task #150). Hypothesis at
the time: a second client somewhere was connecting with the same clientId
(`aevus-edge-needville`), and IoT Core was evicting one or the other on every
new TCP attempt — classic DUPLICATE_CLIENTID churn. Task #150 was unblocked by
renaming the Pi's clientId to `aevus-edge-needville-pi01` in `.env`, but the
ghost slot was left open.

## What we found today (2026-05-30, ~3:00 PM CT)
- **Pi (`aevus-edge`)** holds one stable TCP ESTAB to `98.88.204.61:8883`.
  ~30K msgs/hr publishing, no churn, clientId = `aevus-edge-needville-pi01`.
- **EC2 (`aevus-testbed`)** has `MQTT_ENABLED=false`, no bridge/MQTT procs,
  no :8883 connection. The retired Pi-poll bridge sidecar (Task #94/#98) is
  fully dark.
- **IoT thing** `aevus-edge-needville` — `connected: false` in Fleet Index
  (because Pi connects as `-pi01`, not the bare default).
- **Cert** — exactly 1 ACTIVE cert
  (`6333f8890...efdf71d`), attached to 1 thing, policy `aevus-edge-publish`.
- **CloudWatch metrics** — no `Connect.AuthError`, no
  `ClientDisconnect.Disconnect` activity in the last 14 days. The ghost is
  dormant (or extinct since the rename).

## Root cause of the open slot
The original policy `aevus-edge-publish` v2 allowed
`iot:Connect` on `client/aevus-edge-*` and Publish/Subscribe/Receive on
`aevus/*`. That meant the cert could connect with **any** clientId starting
`aevus-edge-` — including the bare thing name `aevus-edge-needville` — and
publish to **any** site topic. If a copy of the cert ever ended up on another
host (laptop, retired bridge VM, dev machine, container snapshot) and it used
the SDK default clientId (= thing name), it would race the Pi for the slot.

## Fix shipped today

### 1. Policy `aevus-edge-publish` → v3 (default)
Tightened both clientId and topic scopes:

| Resource type | v2 (before) | v3 (after) |
|---|---|---|
| `iot:Connect` | `client/aevus-edge-*` | `client/aevus-edge-needville-*` |
| `iot:Publish`/`PublishRetain` | `topic/aevus/*` | `topic/aevus/needville/*` |
| `iot:Subscribe` | `topicfilter/aevus/*` | `topicfilter/aevus/needville/*` |
| `iot:Receive` | `topic/aevus/*` | `topic/aevus/needville/*` |

Effect:
- The bare `aevus-edge-needville` clientId slot is **closed** — pattern
  `aevus-edge-needville-*` requires a `-<suffix>` after `needville`.
- Any ghost reusing the cert with the SDK-default clientId now gets
  `Connect.AuthError` instead of grabbing the slot.
- Topic scope is now site-bounded (defense-in-depth: even if a future cert
  leak happens, it can't pollute another site's namespace).
- The current Pi (`aevus-edge-needville-pi01`) is unaffected — verified
  publishing continued without interruption right after the policy change.

### 2. CloudWatch alarm `aevus-iot-ghost-connect-rejected`
- Metric: `AWS/IoT Connect.AuthError`, Sum, 5-min, threshold > 0
- Action: SNS topic `aevus-critical-alerts` (→ chiefegr@, woody@)
- Treat missing data: notBreaching (alarm-on-presence)

If a ghost ever returns and gets rejected by the policy, we hear about it
immediately and can hunt the host via CloudTrail.

## Defense-in-depth still in place
- Pi's `.env` keeps `MQTT_CLIENT_ID=aevus-edge-needville-pi01` (the `-pi01`
  suffix is now also enforced by the policy pattern).
- EC2 keeps `MQTT_ENABLED=false`.
- IoT Device Defender Detect baseline (Task #74) catches connection-rate
  anomalies on the fleet.

## Follow-up — Task #149 IaC capture
This policy is **not in Terraform** yet (out-of-band, like the other items
flagged in Task #149). When that task lands, it should `aws_iot_policy` +
`aws_iot_policy_attachment` v3 verbatim, and import the existing resource.
The v3 JSON is at `/tmp/aevus-edge-publish.v2.json` (file name is v2 but
content is v3 — keep in mind on import).

## Verification commands

```bash
# Confirm policy v3 is default
aws iot get-policy --policy-name aevus-edge-publish --query defaultVersionId

# Confirm Pi still publishing
ssh admin@aevus-edge 'journalctl -u aevus -n 5 --since "30 seconds ago" | grep mqtt_published | wc -l'

# Check alarm state
aws cloudwatch describe-alarms --alarm-names aevus-iot-ghost-connect-rejected \
  --query 'MetricAlarms[0].StateValue'
```
