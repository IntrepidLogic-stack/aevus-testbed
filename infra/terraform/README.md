# Aevus AWS Landing Zone — Terraform

Provisions the IoT Core / SiteWise / audit infrastructure that Greengrass v2 edge components publish into.

**Status:** ready to apply once **AWS Activate credits are confirmed** per `docs/AWS_ACTIVATE_CREDITS_CHECK.md`.

---

## What this stands up

| Resource | Purpose |
|---|---|
| `aws_iot_thing` × N | One per edge device. Cloud-side identity. |
| `aws_iot_thing_group` `AevusEdgeDevices` | Deployment target for Greengrass rollouts. |
| `aws_iot_certificate` + `tls_private_key` × N | X.509 mutual-TLS auth, written to `.secrets/` for first-time install. |
| `aws_iot_policy` × N (topic-prefixed) | Each device can only publish under its own `aevus/<site>/...` prefix. |
| `aws_iam_role` `AevusGreengrassV2TokenExchangeRole` | Lets the cert assume runtime perms (S3 artifact pulls, CloudWatch Logs). |
| `aws_iot_role_alias` `AevusGreengrassV2TokenExchangeRoleAlias` | The handle Greengrass uses. |
| `aws_iotsitewise_asset_model` (Cabinet, TrioJR900Radio, SCADAPack470RTU, MikroTikL009Router, CiscoCatalyst2960Switch) | Asset hierarchy with property names matching the polled + DNP3 metric sets. |
| `aws_iotsitewise_asset` `AevusCabinet-<site>` per site | One Cabinet asset per site. Child device assets are seeded by the application, not Terraform. |
| `aws_iot_topic_rule` × 3 (events/alerts/audit → S3) | Routes immutable evidence into the audit bucket. |
| `aws_s3_bucket` `aevus-audit-...` | Object Lock COMPLIANCE mode, 7-year retention by default. |
| `aws_s3_bucket` `aevus-edge-artifacts-...` | Greengrass component zip artifacts. |
| `aws_s3_bucket` `aevus-cloudtrail-...` + `aws_cloudtrail` | Control-plane API audit log, multi-region, signed. |
| `aws_kms_key` `alias/aevus-<env>` | Customer-managed key for all bucket + log encryption. |
| `aws_cloudwatch_log_group` `/aevus/iot/rule-errors` | Where IoT rule failures land for debugging. |

---

## Pre-apply checklist

1. ✅ `docs/AWS_ACTIVATE_CREDITS_CHECK.md` resolved — Activate tier confirmed, credit balance projected against §9 cost estimate.
2. ✅ AWS CLI credentials configured for the account (per IL deployment playbook: `il-admin` profile for first apply).
3. ✅ Terraform ≥ 1.7 installed.
4. ✅ Decide region: us-east-2 (Ohio — closer to Texas) or us-west-2 (Oregon — broader Bedrock model availability). Default is us-east-2.
5. ✅ Pick the environment: `dev` first, `prod` after the lab smoke-test passes.

## First apply

```bash
cd infra/terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

Outputs you'll need:

```bash
terraform output iot_endpoint            # → set as MQTT_BROKER_HOST on the Pi
terraform output edge_certs_path         # → scp these to the Pi
terraform output audit_bucket            # → confirm visible in S3 console
terraform output sitewise_cabinet_assets # → confirm assets in SiteWise console
```

## Connect a Pi to the deployed landing zone

1. From the dev machine:
   ```bash
   # Pull the Amazon Root CA:
   curl -o /tmp/AmazonRootCA1.pem https://www.amazontrust.com/repository/AmazonRootCA1.pem

   # Push CA + the device cert / key to the Pi:
   scp /tmp/AmazonRootCA1.pem pi@aevus-edge:~/aevus-testbed/.certs/
   scp infra/terraform/.secrets/aevus-edge-lab-01.cert.pem pi@aevus-edge:~/aevus-testbed/.certs/
   scp infra/terraform/.secrets/aevus-edge-lab-01.key.pem  pi@aevus-edge:~/aevus-testbed/.certs/
   ```

2. On the Pi, edit `~/aevus-testbed/.env`:
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

3. Restart the scheduler / Greengrass deployment. Watch `aevus/lab/#` in the AWS IoT Core MQTT test client to see messages arriving.

## Tearing it down (dev only)

```bash
terraform destroy
```

Will fail on the audit bucket due to Object Lock — that's intentional. For dev cleanup, set `force_destroy = true` on `aws_s3_bucket.audit` in `aws-audit.tf`, but **never do this in prod**.

## Bedrock RCA Lambda (Phase 6)

Triggered by IoT topic rule on `aevus/+/+/alerts/critical`. Pulls asset context from SiteWise + S3 audit, invokes Claude via Bedrock, publishes the structured narrative back to `aevus/{site}/{asset}/rca/{alert_id}` and appends to S3 audit.

**Source:** `infra/lambda/rca/` — handler, prompt template, context gathering. Packaged into a Lambda zip by `data.archive_file` in `aws-bedrock-rca.tf` — every `terraform apply` after editing the Python files re-deploys the function.

**Bedrock model:** Claude Sonnet by default (`var.bedrock_model_id`). Override to Haiku for lower latency / cost, Opus for deeper reasoning. **Verify model availability in your region** before changing — Bedrock model rollout varies by region.

**First-time setup gates:**

1. **Bedrock model access must be enabled** in the AWS console before `terraform apply`:
   - AWS Console → Bedrock → Model access → Manage model access → enable Anthropic Claude Sonnet (and Haiku as a fallback).
   - This is a one-click but interactive step. Terraform can't accept the EULA on your behalf.

2. **Initial DLQ check:** the Lambda has an SQS dead-letter queue. After deploy, run a synthetic test alarm:
   ```bash
   aws iot-data publish --topic 'aevus/lab/RTU-01/alerts/critical' \
       --cli-binary-format raw-in-base64-out \
       --payload "$(cat tests/lambda/fixtures/synthetic_critical_alert.json)"
   ```
   Check CloudWatch Logs `/aws/lambda/aevus-rca` for processing. Confirm the narrative arrives on `aevus/lab/RTU-01/rca/<id>`.

3. **Confirm latency in the X-Ray trace:** the Lambda enables Active tracing — open the X-Ray service map after the synthetic test to see the end-to-end timing (target: <3s alert → narrative).

## L4E (Lookout for Equipment) pilot

`aws-l4e.tf` provisions the buckets + IAM for a future L4E anomaly-detection model. **Disabled by default** (`var.l4e_enabled = false`) — opt in once we have training data.

L4E requires **14+ days of normal-operation telemetry** per model build. The bootstrap path:

1. Run `scripts/export_l4e_training_data.py` (to be written) — exports historical metrics from InfluxDB to `s3://aevus-l4e-training/...` in L4E's CSV-per-component format.
2. Run `scripts/bootstrap_l4e_model.py` (to be written) — calls `boto3.client('lookoutequipment')` to:
   - `CreateDataset` against the training bucket
   - `CreateModel` with the schema mapping
   - `CreateInferenceScheduler` writing to `s3://aevus-l4e-inference/...`
3. A separate Lambda (next round) watches the inference bucket and re-publishes anomaly scores onto `aevus/{site}/{asset}/events/anomaly` — flows back into the alert engine via the existing publisher path.

Terraform's AWS provider doesn't yet have native `aws_lookoutequipment_*` resources, so model creation is a one-shot script rather than a managed resource.

## What's not in here yet

- AppSync GraphQL API for the dashboard MQTT-over-WSS subscriptions (next phase).
- The L4E model creation scripts (need 14 days of data first).
- A separate Lambda to forward L4E inference scores into the alert engine.
- Per-device SiteWise asset registration (data-driven, lives in the application).

## File layout

```
infra/terraform/
├── versions.tf             # provider + backend setup
├── variables.tf            # region, sites, edge_devices, retention, bedrock model
├── outputs.tf              # IoT endpoint, bucket names, asset IDs
├── aws-iot-core.tf         # Things, certs, policies, token exchange role
├── aws-iot-rules.tf        # MQTT → S3 / DynamoDB / SiteWise routing
├── aws-sitewise.tf         # asset models + per-site Cabinet asset
├── aws-bedrock-rca.tf      # Phase 6 — RCA Lambda + IoT trigger
├── aws-l4e.tf              # Phase 6 — Lookout for Equipment pilot (opt-in)
├── aws-audit.tf            # audit bucket, artifacts bucket, KMS, CloudTrail
├── .gitignore              # state files + .secrets/ + .build/
└── README.md               # this file

infra/lambda/rca/
├── handler.py              # IoT rule action handler
├── prompt.py               # Bedrock prompt template + response parser
├── context.py              # SiteWise + S3 audit context gathering
└── requirements.txt        # placeholder (stdlib + boto3 only)
```
