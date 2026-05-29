# Phase 1 — Latest-State Store (DynamoDB + IoT Rule)

Part of the edge→cloud convergence (see
`docs/ARCHITECTURE_edge_to_cloud_convergence_v1.md` §5, Phase 1).

## What this creates

| Resource | Purpose |
|---|---|
| `aws_dynamodb_table.aevus-latest-state` | Per-asset/metric last-known-value (PK=`asset_id`, SK=`metric`), on-demand billing, PITR on |
| `aws_iot_topic_rule.aevus_latest_state_to_ddb` | Subscribes `aevus/+/+/telemetry/+`, upserts each reading into the table |
| `aws_iam_role.aevus-iot-latest-state-ddb` | Role the rule assumes to `PutItem` + write error logs |
| `aws_cloudwatch_log_group` `/aws/iot/aevus-latest-state-errors` | Rule-failure visibility (14-day retention) |

**Standalone + additive.** Does NOT manage the existing IoT Core landing zone
(thing `aevus-edge-needville`; rules `aevus_archive_all` / `_critical_to_sns` /
`_critical_to_rca`). It only adds the resources above. Nothing existing changes.

## Why

The edge already publishes telemetry to IoT Core (`aevus/#` → S3 archive is
live). Phase 1 forks that same stream into a queryable current-state store so
the dashboard's read-API (Phase 2) can serve current values from a
stream-backed table — no cloud-side OT polling, no SQLite-copy bridge.

## Data shape

Topic `aevus/{site}/{asset}/telemetry/{metric}` →

```
{ asset_id: "RAD-01", metric: "rssi", site: "needville",
  value: -143.0, unit: "dBm", source: "snmp", updated_ms: 1748...}
```

A query on `asset_id = RAD-01` returns that radio's full current vital set.

## Apply

```bash
cd infra/terraform/phase1-latest-state
AWS_PROFILE=il-admin terraform init
AWS_PROFILE=il-admin terraform plan -out tf.plan
AWS_PROFILE=il-admin terraform apply tf.plan

# Verify telemetry is landing (within ~1 poll cycle):
AWS_PROFILE=il-admin aws dynamodb scan --table-name aevus-latest-state \
  --max-items 5 --region us-east-1
```

## Prerequisite check

The edge must actually be publishing telemetry (not just alerts) to IoT Core —
i.e. `mqtt_enabled=true` on the Pi with telemetry topics flowing. Confirm the
S3 archive has recent `aevus/needville/*/telemetry/*` objects, or scan the table
after apply. If empty, the edge's `mqtt_enabled` / telemetry publish is the gap
to close first (not this module).

## Next (Phase 2)

Point the cloud read-API (`/api/v1/assets`) at this table for current values +
SiteWise for history, replacing the local SQLite read path. Then Phase 3 stops
EC2 polling OT; Phase 4 retires `aevus_bridge_v2.py`.
